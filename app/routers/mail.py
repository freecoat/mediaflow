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
from app.models.models import User
from app.services.rbac import current_user
from app.services.oauth_providers import get_token
from app.services import gmail

router = APIRouter(tags=["mail"])

# gmail.modify include lettura; gmail.readonly resta valido per account già connessi.
_GMAIL_READ_SCOPES = ("gmail.modify", "gmail.readonly")


@router.get("/mail")
async def mail_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse("pages/mail.html", {"request": request, "active_page": "mail"})


@router.get("/mail/api/status")
async def mail_status(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    token = get_token(db, user.id, "google")
    scopes = (token.scopes or "") if token else ""
    connected = bool(token and any(s in scopes for s in _GMAIL_READ_SCOPES))
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
async def mail_labels(request: Request, counts: bool = False, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"labels": gmail.list_labels(db, user.id, counts=counts)}


@router.post("/mail/api/threads/action")
async def mail_threads_action(request: Request, db: Session = Depends(get_db),
                              thread_ids: str = Form(...), action: str = Form(...),
                              label_id: Optional[str] = Form(None)):
    """Azione (letto/stella/archivia/cestino/sposta/etichetta) su uno o più thread."""
    user = current_user(request)
    ids = [t.strip() for t in thread_ids.split(",") if t.strip()]
    return gmail.apply_action(db, user.id, ids, action, label_id=label_id)


@router.get("/mail/api/signature")
async def mail_get_signature(request: Request, db: Session = Depends(get_db)):
    """Firma email HTML per-utente (auto-inserita nel compose)."""
    user = current_user(request)
    u = db.get(User, user.id)
    return {"signature": (u.email_signature if u else None) or ""}


@router.post("/mail/api/signature")
async def mail_set_signature(request: Request, db: Session = Depends(get_db),
                             signature: str = Form("")):
    user = current_user(request)
    u = db.get(User, user.id)
    if u:
        u.email_signature = signature or None
        db.commit()
    return {"ok": True}


@router.get("/mail/api/contacts")
async def mail_contacts(request: Request, db: Session = Depends(get_db)):
    """Rubrica per autocomplete indirizzi (People API). Best-effort."""
    user = current_user(request)
    return {"contacts": gmail.list_contacts(db, user.id)}


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
