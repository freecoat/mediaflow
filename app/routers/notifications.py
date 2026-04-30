"""Router notifiche utente (v3.4.27).

Endpoint REST per il drawer notifiche e il badge counter in topbar.
Tutte le rotte richiedono autenticazione; nessun permesso speciale —
ogni utente vede SOLO le proprie notifiche (filter su `user_id == me.id`).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Notification, User
from app.services import notifications as notif_svc
from app.services.rbac import current_user, current_user_optional


router = APIRouter(prefix="/notifications", tags=["notifications"])


def _n_dict(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "severity": n.severity,
        "title": n.title,
        "body": n.body,
        "link": n.link,
        "payload": n.payload,
        "is_read": n.is_read,
        "is_archived": n.is_archived,
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "actor_user_id": n.actor_user_id,
    }


@router.get("/api/unread-count")
async def get_unread_count(
    request: Request,
    db: Session = Depends(get_db),
):
    """Lightweight: solo {total, action_required}. Polling 30s."""
    user = current_user_optional(request)
    if not user:
        return {"total": 0, "action_required": 0}
    return notif_svc.unread_count(db, user)


@router.get("/api/list")
async def list_notifications(
    request: Request,
    only_unread: bool = False,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    user = current_user(request)
    items = notif_svc.list_for_user(
        db, user,
        only_unread=only_unread,
        include_archived=include_archived,
        limit=min(limit, 200), offset=offset,
    )
    return [_n_dict(n) for n in items]


@router.post("/api/{notification_id}/read")
async def mark_one_read(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user(request)
    n = notif_svc.mark_read(db, user, [notification_id])
    return {"updated": n}


@router.post("/api/mark-all-read")
async def mark_all_read(
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user(request)
    n = notif_svc.mark_all_read(db, user)
    return {"updated": n}


@router.delete("/api/{notification_id}")
async def archive_notification(
    notification_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    user = current_user(request)
    ok = notif_svc.archive(db, user, notification_id)
    if not ok:
        raise HTTPException(404, "Notifica non trovata")
    return {"ok": True}
