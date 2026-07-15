# app/routers/email_links.py
"""Router email agganciate — Client email Sotto-fase 2 (v3.5.0-alpha.172.245).

Aggancia thread Gmail alle trattative (acquisitions): pin (thread_id o URL),
list, delete + Activity(type=email) automatica. Tenant-scoped, soft-delete,
RBAC acquisitions. Best-effort: metadata non accessibili → fallback subject."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.context import current_tenant_id
from app.models.models import (EmailLink, Acquisition, Activity, ActivityType,
                               ActivityDirection)
from app.services.rbac import current_user, has_permission
from app.services.tenant_guard import scoped, fetch_or_404
from app.services import gmail
from app.services.clock import now_utc

router = APIRouter(tags=["email-links"])


def _serialize_email(e: EmailLink) -> dict:
    return {"id": e.id, "thread_id": e.thread_id, "message_id": e.message_id,
            "from_addr": e.from_addr, "subject": e.subject, "snippet": e.snippet,
            "email_date": e.email_date, "acquisition_id": e.acquisition_id}


@router.post("/acquisitions/api/{aid}/emails/link")
async def pin_email(aid: int, request: Request, db: Session = Depends(get_db),
                    url: Optional[str] = Form(None), thread_id: Optional[str] = Form(None),
                    message_id: Optional[str] = Form(None), from_addr: Optional[str] = Form(None),
                    subject: Optional[str] = Form(None), snippet: Optional[str] = Form(None),
                    email_date: Optional[str] = Form(None)):
    user = current_user(request)
    if not has_permission(user, "manage_acquisitions"):
        raise HTTPException(403, "Permesso negato")
    fetch_or_404(db, Acquisition, aid)

    tid = (thread_id or "").strip()
    if not tid and url:
        tid = gmail.parse_gmail_thread_id(url) or ""
        if not tid:
            raise HTTPException(400, "Link Gmail non valido")
    if not tid:
        raise HTTPException(400, "thread_id o url richiesto")

    d_from, d_subj, d_snip, d_date, d_msg = from_addr, subject, snippet, email_date, message_id
    if not d_subj:  # best-effort metadata dal primo messaggio
        thr = gmail.get_thread(db, user.id, tid)
        msgs = (thr or {}).get("messages") or []
        if msgs:
            m0 = msgs[0]
            d_from = d_from or m0.get("from")
            d_subj = d_subj or m0.get("subject")
            d_snip = d_snip or m0.get("snippet")
            d_date = d_date or m0.get("date")
            d_msg = d_msg or m0.get("id")
    if not d_subj:
        d_subj = "Email"

    link = EmailLink(tenant_id=current_tenant_id(), provider="google", thread_id=tid,
                     message_id=d_msg, from_addr=d_from, subject=d_subj, snippet=d_snip,
                     email_date=d_date, acquisition_id=aid, added_by=user.id)
    db.add(link)
    # Activity(type=email) automatica sulla timeline trattativa
    db.add(Activity(tenant_id=current_tenant_id(), acquisition_id=aid,
                    type=ActivityType.email, direction=ActivityDirection.inbound,
                    subject=d_subj, body=d_snip, occurred_at=now_utc(),
                    created_by=user.id, ai_extracted=False))
    db.commit(); db.refresh(link)
    return _serialize_email(link)


@router.get("/acquisitions/api/{aid}/emails")
async def list_emails(aid: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not has_permission(user, "view_acquisitions"):
        raise HTTPException(403, "Permesso negato")
    q = scoped(db.query(EmailLink), EmailLink).filter(
        EmailLink.acquisition_id == aid, EmailLink.is_active == True,  # noqa: E712
    ).order_by(EmailLink.created_at.desc())
    return {"emails": [_serialize_email(e) for e in q.all()]}


@router.delete("/email-links/{link_id}")
async def delete_email(link_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not has_permission(user, "manage_acquisitions"):
        raise HTTPException(403, "Permesso negato")
    link = fetch_or_404(db, EmailLink, link_id)
    link.is_active = False
    db.commit()
    return {"ok": True}
