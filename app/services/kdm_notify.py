"""Notifica finishing alla nuova richiesta KDM: in-app (manage_kdm) + email."""
from __future__ import annotations
import os

from app.services.notifications import notify_permission


def _send_email_safe(subject: str, body: str, to_addrs: list) -> None:
    """Best-effort SMTP. Silenzioso se SMTP non configurato (.env SMTP_HOST vuoto)."""
    if not os.environ.get("SMTP_HOST", "").strip() or not to_addrs:
        return
    try:
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))
        msg["To"] = ", ".join(to_addrs)
        msg.set_content(body)
        port = int(os.environ.get("SMTP_PORT", "587"))
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20) as srv:
            if os.environ.get("SMTP_USE_TLS", "1") == "1":
                srv.starttls()
            user = os.environ.get("SMTP_USER", "")
            if user:
                srv.login(user, os.environ.get("SMTP_PASS", ""))
            srv.send_message(msg)
    except Exception:
        return  # mai bloccare il flusso per un'email


def _finishing_emails(db, tenant_id: int) -> list:
    """Email degli utenti attivi con permesso manage_kdm (best-effort)."""
    try:
        from app.models import User
        from app.services.rbac import has_permission
        users = db.query(User).filter(User.is_active == True).all()  # noqa: E712
        return [
            u.email for u in users
            if getattr(u, "email", None) and has_permission(u, "manage_kdm")
        ]
    except Exception:
        return []


def notify_new_kdm_request(db, req) -> None:
    """Notifica tutti i finishing (manage_kdm) di una nuova richiesta KDM/DKDM."""
    title = getattr(req, "requested_title", None) \
        or getattr(req, "requested_cpl_uuid", None) \
        or f"#{req.id}"
    kind = (getattr(req, "request_type", None) or "kdm").upper()
    msg = f"Nuova richiesta {kind}: {title}"
    tenant_id = getattr(req, "tenant_id", 1)

    # In-app a tutti gli utenti con manage_kdm
    notify_permission(
        db,
        permission="manage_kdm",
        kind="kdm_request",
        title="Richiesta KDM/DKDM",
        body=msg,
        link="/kdm",
        severity="info",
        tenant_id=tenant_id,
    )

    # Email best-effort (mai solleva eccezioni)
    _send_email_safe(
        f"[Claqo] {msg}",
        msg + "\n\nApri Claqo → /kdm",
        _finishing_emails(db, tenant_id),
    )
