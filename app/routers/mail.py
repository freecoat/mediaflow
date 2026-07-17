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
from app.services.ai_provider import get_provider_for_user
from app.services import gmail

router = APIRouter(tags=["mail"])

# gmail.modify include lettura; gmail.readonly resta valido per account già connessi.
_GMAIL_READ_SCOPES = ("gmail.modify", "gmail.readonly")


# Default preferenze client email. Chiavi note; salvate in users.mail_prefs (JSON).
MAIL_PREFS_DEFAULTS = {
    "mark_read_on_open": True,
    "autosave": True,
    "auto_refresh_sec": 120,
    "compose_new_window": False,
    "default_font": "Arial, sans-serif",
}


@router.get("/mail")
async def mail_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse("pages/mail.html", {"request": request, "active_page": "mail"})


@router.get("/mail/compose")
async def mail_compose_page(request: Request):
    """Finestra compose standalone (pop-out via window.open)."""
    from app.main import templates
    return templates.TemplateResponse("pages/mail_compose.html", {"request": request, "active_page": "mail"})


@router.get("/mail/api/prefs")
async def mail_get_prefs(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    u = db.get(User, user.id)
    prefs = dict(MAIL_PREFS_DEFAULTS)
    if u and isinstance(u.mail_prefs, dict):
        prefs.update({k: v for k, v in u.mail_prefs.items() if k in MAIL_PREFS_DEFAULTS})
    return {"prefs": prefs}


@router.post("/mail/api/prefs")
async def mail_set_prefs(request: Request, db: Session = Depends(get_db),
                         mark_read_on_open: Optional[str] = Form(None),
                         autosave: Optional[str] = Form(None),
                         auto_refresh_sec: Optional[int] = Form(None),
                         compose_new_window: Optional[str] = Form(None),
                         default_font: Optional[str] = Form(None)):
    user = current_user(request)
    u = db.get(User, user.id)
    if not u:
        return {"ok": False}
    prefs = dict(u.mail_prefs) if isinstance(u.mail_prefs, dict) else {}
    def _bool(v):  # checkbox: "1"/"true"/"on" → True, altrimenti False
        return str(v).lower() in ("1", "true", "on", "yes")
    if mark_read_on_open is not None:
        prefs["mark_read_on_open"] = _bool(mark_read_on_open)
    if autosave is not None:
        prefs["autosave"] = _bool(autosave)
    if compose_new_window is not None:
        prefs["compose_new_window"] = _bool(compose_new_window)
    if auto_refresh_sec is not None:
        prefs["auto_refresh_sec"] = max(0, min(3600, auto_refresh_sec))  # 0 = off
    if default_font is not None:
        prefs["default_font"] = default_font[:80]
    u.mail_prefs = prefs
    db.commit()
    merged = dict(MAIL_PREFS_DEFAULTS); merged.update(prefs)
    return {"ok": True, "prefs": merged}


@router.get("/mail/api/status")
async def mail_status(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    token = get_token(db, user.id, "google")
    scopes = (token.scopes or "") if token else ""
    connected = bool(token and any(s in scopes for s in _GMAIL_READ_SCOPES))
    return {"connected": connected,
            "account_email": token.account_email if (token and connected) else None,
            "mail_full": gmail.has_mail_full_scope(token)}


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


@router.post("/mail/api/labels")
async def mail_label_create(request: Request, db: Session = Depends(get_db),
                            name: str = Form(...), parent: Optional[str] = Form(None)):
    """Crea etichetta/cartella (annidata se `parent`)."""
    user = current_user(request)
    res = gmail.create_label(db, user.id, name, parent=parent)
    if not res:
        return {"ok": False}
    return {"ok": True, "label": res}


@router.put("/mail/api/labels/{label_id}")
async def mail_label_rename(label_id: str, request: Request, db: Session = Depends(get_db),
                            name: str = Form(...)):
    """Rinomina/sposta etichetta (name = nome pieno con eventuale Parent/)."""
    user = current_user(request)
    res = gmail.rename_label(db, user.id, label_id, name)
    if not res:
        return {"ok": False}
    return {"ok": True, "label": res}


@router.delete("/mail/api/labels/{label_id}")
async def mail_label_delete(label_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"ok": gmail.delete_label(db, user.id, label_id)}


@router.get("/mail/api/filters")
async def mail_filters_list(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"filters": gmail.list_filters(db, user.id)}


@router.post("/mail/api/filters")
async def mail_filter_create(request: Request, db: Session = Depends(get_db),
                             from_addr: Optional[str] = Form(None), to_addr: Optional[str] = Form(None),
                             subject: Optional[str] = Form(None), query: Optional[str] = Form(None),
                             has_attachment: Optional[str] = Form(None),
                             add_label_id: Optional[str] = Form(None),
                             mark_read: Optional[str] = Form(None), star: Optional[str] = Form(None),
                             archive: Optional[str] = Form(None)):
    """Crea un filtro Gmail: criteri (da/a/oggetto/query/allegati) + azioni."""
    user = current_user(request)
    def _b(v): return str(v).lower() in ("1", "true", "on", "yes")
    criteria = {"from": from_addr, "to": to_addr, "subject": subject, "query": query,
                "hasAttachment": _b(has_attachment) if has_attachment is not None else False}
    add, rem = [], []
    if add_label_id:
        add.append(add_label_id)
    if mark_read is not None and _b(mark_read):
        rem.append("UNREAD")
    if star is not None and _b(star):
        add.append("STARRED")
    if archive is not None and _b(archive):
        rem.append("INBOX")
    action = {"addLabelIds": add, "removeLabelIds": rem}
    res = gmail.create_filter(db, user.id, criteria, action)
    if not res:
        return {"ok": False}
    return {"ok": True, "filter": res}


@router.delete("/mail/api/filters/{filter_id}")
async def mail_filter_delete(filter_id: str, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"ok": gmail.delete_filter(db, user.id, filter_id)}


def _date_to_ms(d: Optional[str]) -> Optional[int]:
    """'YYYY-MM-DD' → epoch ms (mezzanotte UTC). None se vuoto/invalido."""
    if not d:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


@router.get("/mail/api/vacation")
async def mail_vacation_get(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    return {"vacation": gmail.get_vacation(db, user.id)}


@router.post("/mail/api/vacation")
async def mail_vacation_set(request: Request, db: Session = Depends(get_db),
                            enabled: Optional[str] = Form(None), subject: str = Form(""),
                            body: str = Form(""), restrict_contacts: Optional[str] = Form(None),
                            start: Optional[str] = Form(None), end: Optional[str] = Form(None)):
    """Imposta/disattiva la risposta automatica (vacation responder)."""
    user = current_user(request)
    def _b(v): return str(v).lower() in ("1", "true", "on", "yes")
    res = gmail.set_vacation(db, user.id, enabled=_b(enabled), subject=subject, body_html=body,
                             restrict_to_contacts=_b(restrict_contacts),
                             start_ms=_date_to_ms(start), end_ms=_date_to_ms(end))
    if res is None:
        return {"ok": False}
    return {"ok": True, "vacation": res}


# ── AI copilot mail (Sotto-fase 4) — provider.complete per-utente ──────

def _strip_fences(txt: str) -> str:
    """Rimuove eventuali ```...``` che il modello può avvolgere attorno all'output."""
    t = (txt or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


@router.post("/mail/api/ai/reply")
async def mail_ai_reply(request: Request, db: Session = Depends(get_db),
                        thread_id: str = Form(...), instruction: str = Form("")):
    """Genera una bozza di risposta HTML per un thread (AI propone, utente invia)."""
    user = current_user(request)
    provider = get_provider_for_user(user.id, db)
    if not provider:
        return {"ok": False, "error": "no_provider"}
    thr = gmail.get_thread(db, user.id, thread_id)
    if not thr or not thr.get("messages"):
        return {"ok": False, "error": "no_thread"}
    msgs = thr["messages"]
    last = msgs[-1]
    convo = "\n\n---\n\n".join(
        f"Da: {m.get('from', '')}\nOggetto: {m.get('subject', '')}\n{(m.get('body_text') or '')[:4000]}"
        for m in msgs[-4:])
    system = ("Sei un assistente email professionale italiano. Scrivi SOLO il corpo HTML "
              "(usa <p>, <br>, <b>, <ul><li>) di una bozza di risposta, tono professionale e "
              "conciso. NON inventare fatti, date o impegni non presenti nel thread. Niente "
              "oggetto, niente firma, niente commenti fuori dall'HTML.")
    user_prompt = (f"Conversazione:\n{convo}\n\nIstruzioni per la risposta: "
                   f"{instruction.strip() or 'Rispondi in modo appropriato al mittente.'}")
    try:
        raw = _strip_fences(provider.complete(system, user_prompt, max_tokens=1500, temperature=0.5))
    except Exception as e:
        return {"ok": False, "error": "ai_failed"}
    # Output AI = non fidato (prompt injection dal corpo email): sanitizza prima
    # che finisca in innerHTML del compose e nel messaggio inviato.
    html = gmail.sanitize_html(raw)
    subj = last.get("subject") or ""
    return {"ok": True, "html": html, "thread_id": thread_id,
            "to": last.get("from") or "",
            "subject": subj if subj.lower().startswith("re:") else ("Re: " + subj)}


@router.post("/mail/api/ai/search")
async def mail_ai_search(request: Request, db: Session = Depends(get_db), q: str = Form(...)):
    """Traduce una richiesta in linguaggio naturale in una query di ricerca Gmail."""
    user = current_user(request)
    provider = get_provider_for_user(user.id, db)
    if not provider:
        return {"ok": False, "error": "no_provider"}
    system = ("Converti la richiesta dell'utente in UNA query di ricerca Gmail valida usando "
              "gli operatori (from: to: subject: has:attachment after:YYYY/MM/DD before:YYYY/MM/DD "
              "is:unread is:starred label:). Rispondi SOLO con la query, senza spiegazioni, "
              "senza virgolette, su una sola riga.")
    try:
        query = _strip_fences(provider.complete(system, q, max_tokens=80, temperature=0.0))
    except Exception:
        return {"ok": False, "error": "ai_failed"}
    query = query.replace("\n", " ").strip().strip('"').strip("`")
    return {"ok": True, "query": query}


@router.post("/mail/api/threads/action")
async def mail_threads_action(request: Request, db: Session = Depends(get_db),
                              thread_ids: str = Form(...), action: str = Form(...),
                              label_id: Optional[str] = Form(None)):
    """Azione (letto/stella/archivia/cestino/sposta/etichetta) su uno o più thread.
    `delete_forever` è IRREVERSIBILE: gate su scope pieno (α.172.263)."""
    user = current_user(request)
    ids = [t.strip() for t in thread_ids.split(",") if t.strip()]
    if action == "delete_forever":
        token = get_token(db, user.id, "google")
        if not gmail.has_mail_full_scope(token):
            raise HTTPException(403, "Serve lo scope Gmail pieno: attiva la gestione "
                                     "avanzata email in Impostazioni")
        ok, failed = 0, 0
        for tid in ids:
            if gmail.delete_thread_forever(db, user.id, tid):
                ok += 1
            else:
                failed += 1
        return {"ok": ok, "failed": failed}
    return gmail.apply_action(db, user.id, ids, action, label_id=label_id)


@router.post("/mail/api/trash/empty")
async def mail_empty_trash(request: Request, db: Session = Depends(get_db)):
    """Svuota cestino: IRREVERSIBILE. Gate su scope pieno (α.172.263)."""
    user = current_user(request)
    token = get_token(db, user.id, "google")
    if not gmail.has_mail_full_scope(token):
        raise HTTPException(403, "Serve lo scope Gmail pieno: attiva la gestione "
                                 "avanzata email in Impostazioni")
    return gmail.empty_trash(db, user.id)


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


@router.put("/mail/api/draft/{draft_id}")
async def mail_draft_update(draft_id: str, request: Request, db: Session = Depends(get_db),
                            to: str = Form(""), subject: str = Form(""), body: str = Form(""),
                            cc: Optional[str] = Form(None), bcc: Optional[str] = Form(None),
                            thread_id: Optional[str] = Form(None),
                            in_reply_to: Optional[str] = Form(None),
                            references: Optional[str] = Form(None),
                            attachments: Optional[List[UploadFile]] = File(None)):
    """Aggiorna una bozza esistente (autosave debounced dal compose)."""
    user = current_user(request)
    atts = await _collect_attachments(attachments)
    res = gmail.update_draft(db, user.id, draft_id, to=to, subject=subject, body_html=body,
                             cc=cc, bcc=bcc, thread_id=thread_id, in_reply_to=in_reply_to,
                             references=references, attachments=atts or None)
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
