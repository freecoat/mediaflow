"""Servizio notifiche centralizzato (v3.4.27).

Single point per emettere notifiche utente. Ogni evento "interessante" del
sistema (richiesta ferie pending, conflitto booking, deadline progetto)
chiama qui per generare le row Notification destinate agli utenti corretti.

Pattern broadcast:
- `notify(user_ids=[...])` → consegna a una lista di user_id
- `notify_permission(permission="approve_unavailability")` → consegna a tutti
  gli utenti che hanno quel permesso (via ruolo o extra_permissions)
- `notify_role(role_codes=["admin", "manager"])` → consegna a tutti gli utenti
  con quei ruoli

Pattern una-row-per-destinatario: più semplice per unread_count, mark_read,
filtri per-user. Multi-recipient = N rows (peso trascurabile, retention 90gg).
"""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    Notification, NotificationKind, NotificationSeverity,
    User, Role,
)


def notify(
    db: Session,
    *,
    user_ids: Iterable[int],
    kind: str,
    title: str,
    severity: str = "info",
    body: Optional[str] = None,
    link: Optional[str] = None,
    payload: Optional[dict] = None,
    actor_user_id: Optional[int] = None,
    tenant_id: int = 1,
    commit: bool = True,
) -> List[Notification]:
    """Emit notifications to a list of user_ids. Idempotente solo nel senso
    che N chiamate = N notifiche (no dedup automatico)."""
    user_ids = list({int(u) for u in user_ids if u})
    if not user_ids:
        return []
    out: List[Notification] = []
    for uid in user_ids:
        n = Notification(
            tenant_id=tenant_id,
            user_id=uid,
            actor_user_id=actor_user_id,
            kind=kind,
            severity=severity,
            title=title,
            body=body,
            link=link,
            payload=payload,
        )
        db.add(n)
        out.append(n)
    if commit:
        db.commit()
        for n in out:
            db.refresh(n)
    return out


def notify_permission(
    db: Session,
    *,
    permission: str,
    exclude_user_ids: Optional[Iterable[int]] = None,
    **kwargs,
) -> List[Notification]:
    """Emit a tutti gli utenti attivi che hanno `permission` (via ruolo o extra)."""
    from app.services.rbac import has_permission
    excl = set(int(u) for u in (exclude_user_ids or []))
    users = (
        db.query(User)
        .filter(User.is_active == True)  # noqa: E712
        .all()
    )
    target_ids = [u.id for u in users if has_permission(u, permission) and u.id not in excl]
    return notify(db, user_ids=target_ids, **kwargs)


def notify_role(
    db: Session,
    *,
    role_codes: Sequence[str],
    exclude_user_ids: Optional[Iterable[int]] = None,
    **kwargs,
) -> List[Notification]:
    """Emit a tutti gli utenti con uno dei role.code indicati."""
    excl = set(int(u) for u in (exclude_user_ids or []))
    role_codes = [c.lower() for c in role_codes]
    role_ids = [r.id for r in db.query(Role).filter(Role.code.in_(role_codes)).all()]
    if not role_ids:
        return []
    users = (
        db.query(User)
        .filter(User.is_active == True, User.role_id.in_(role_ids))  # noqa: E712
        .all()
    )
    target_ids = [u.id for u in users if u.id not in excl]
    return notify(db, user_ids=target_ids, **kwargs)


# ── Mark/list helpers ───────────────────────────────────────────────
def mark_read(db: Session, user: User, notification_ids: Iterable[int]) -> int:
    ids = [int(i) for i in notification_ids if i]
    if not ids:
        return 0
    n = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.id.in_(ids),
            Notification.is_read == False,  # noqa: E712
        )
        .update({"is_read": True, "read_at": datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    return n


def mark_all_read(db: Session, user: User) -> int:
    n = (
        db.query(Notification)
        .filter(
            Notification.user_id == user.id,
            Notification.is_read == False,  # noqa: E712
        )
        .update({"is_read": True, "read_at": datetime.utcnow()}, synchronize_session=False)
    )
    db.commit()
    return n


def archive(db: Session, user: User, notification_id: int) -> bool:
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if not n:
        return False
    n.is_archived = True
    if not n.is_read:
        n.is_read = True
        n.read_at = datetime.utcnow()
    db.commit()
    return True


def unread_count(db: Session, user: User) -> dict:
    """Ritorna {total, action_required} non-letti non-archiviati per l'utente."""
    base = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,  # noqa: E712
        Notification.is_archived == False,  # noqa: E712
    )
    total = base.count()
    action = base.filter(Notification.severity == NotificationSeverity.action_required.value).count()
    return {"total": total, "action_required": action}


def list_for_user(
    db: Session,
    user: User,
    *,
    only_unread: bool = False,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> List[Notification]:
    q = db.query(Notification).filter(Notification.user_id == user.id)
    if not include_archived:
        q = q.filter(Notification.is_archived == False)  # noqa: E712
    if only_unread:
        q = q.filter(Notification.is_read == False)  # noqa: E712
    return q.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()


# ── Retention cleanup ──────────────────────────────────────────────
def cleanup_old(db: Session, days: int = 90) -> int:
    """Soft-archive notifiche lette più vecchie di N giorni. Idempotente.

    Da chiamare periodicamente (cron / lifespan startup). Non distrugge dati,
    solo flag is_archived=True. Per hard-delete usare un secondo passaggio.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    n = (
        db.query(Notification)
        .filter(
            Notification.is_read == True,  # noqa: E712
            Notification.is_archived == False,  # noqa: E712
            Notification.read_at < cutoff,
        )
        .update({"is_archived": True}, synchronize_session=False)
    )
    db.commit()
    return n
