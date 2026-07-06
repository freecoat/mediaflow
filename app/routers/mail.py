# app/routers/mail.py
"""Router client email — Client email Sotto-fase 1 (v3.5.0-alpha.172.244).

Pagina /mail = webmail standalone su Gmail. Proxy stateless (nessuno storage
locale). Contenuto per-utente (non tenant-scoped). Best-effort: chiamate Gmail
fallite → risposta vuota, mai 500."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.rbac import current_user
from app.services.oauth_providers import get_token
from app.services import gmail

router = APIRouter(tags=["mail"])

_GMAIL_READ_SCOPE = "gmail.readonly"


@router.get("/mail")
async def mail_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse("pages/mail.html", {"request": request, "active_page": "mail"})


@router.get("/mail/api/status")
async def mail_status(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    token = get_token(db, user.id, "google")
    connected = bool(token and _GMAIL_READ_SCOPE in (token.scopes or ""))
    return {"connected": connected,
            "account_email": token.account_email if (token and connected) else None}


@router.get("/mail/api/threads")
async def mail_threads(request: Request, label: Optional[str] = None, q: Optional[str] = None,
                       page_token: Optional[str] = None, db: Session = Depends(get_db)):
    user = current_user(request)
    label_ids = label if label else None
    return gmail.list_threads(db, user.id, query=q, label_ids=label_ids, page_token=page_token)


@router.get("/mail/api/thread/{thread_id}")
async def mail_thread(thread_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    thr = gmail.get_thread(db, user.id, thread_id)
    if thr is None:
        raise HTTPException(404, "Thread non trovato o non accessibile")
    return thr


@router.get("/mail/api/labels")
async def mail_labels(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"labels": gmail.list_labels(db, user.id)}


@router.get("/mail/api/attachment/{message_id}/{attachment_id}")
async def mail_attachment(message_id: str, attachment_id: str, request: Request,
                          filename: str = "allegato", mime: str = "application/octet-stream",
                          db: Session = Depends(get_db)):
    user = current_user(request)
    data = gmail.get_attachment(db, user.id, message_id, attachment_id)
    if data is None:
        raise HTTPException(404, "Allegato non disponibile")
    safe_name = filename.replace('"', "").replace("\n", "").replace("\r", "")
    return Response(content=data, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{safe_name}"'})


async def _collect_attachments(files: Optional[list]) -> list:
    out = []
    for f in files or []:
        if not f:
            continue
        data = await f.read()
        if not data and not (f.filename or ""):
            continue
        out.append({"filename": f.filename or "allegato",
                    "mime_type": f.content_type or "application/octet-stream", "data": data})
    return out


@router.post("/mail/api/send")
async def mail_send(request: Request, db: Session = Depends(get_db),
                    to: str = Form(...), subject: str = Form(""), body: str = Form(""),
                    cc: Optional[str] = Form(None), bcc: Optional[str] = Form(None),
                    thread_id: Optional[str] = Form(None), in_reply_to: Optional[str] = Form(None),
                    references: Optional[str] = Form(None),
                    attachments: Optional[List[UploadFile]] = File(None)):
    user = current_user(request)
    atts = await _collect_attachments(attachments)
    res = gmail.send_message(db, user.id, to=to, subject=subject, body_html=body, cc=cc, bcc=bcc,
                             thread_id=thread_id, in_reply_to=in_reply_to, references=references,
                             attachments=atts or None)
    if not res:
        return {"ok": False}
    return {"ok": True, "id": res.get("id"), "thread_id": res.get("threadId")}


@router.post("/mail/api/draft")
async def mail_draft_create(request: Request, db: Session = Depends(get_db),
                            to: str = Form(""), subject: str = Form(""), body: str = Form(""),
                            cc: Optional[str] = Form(None), bcc: Optional[str] = Form(None),
                            thread_id: Optional[str] = Form(None),
                            in_reply_to: Optional[str] = Form(None),
                            references: Optional[str] = Form(None),
                            attachments: Optional[List[UploadFile]] = File(None)):
    user = current_user(request)
    atts = await _collect_attachments(attachments)
    res = gmail.save_draft(db, user.id, to=to, subject=subject, body_html=body, cc=cc, bcc=bcc,
                           thread_id=thread_id, in_reply_to=in_reply_to, references=references,
                           attachments=atts or None)
    if not res:
        return {"ok": False}
    return {"ok": True, "id": res.get("id")}


@router.get("/mail/api/drafts")
async def mail_drafts(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"drafts": gmail.list_drafts(db, user.id)}


@router.delete("/mail/api/draft/{draft_id}")
async def mail_draft_delete(draft_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"ok": gmail.delete_draft(db, user.id, draft_id)}
