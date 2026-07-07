# app/services/gmail.py
"""Gmail API client — Client email Sotto-fase 1 (v3.5.0-alpha.172.244).

Layer HTTP isolato (urllib, coerente con google_drive.py/google_calendar.py).
Unico `_gmail_request` = punto di mock. Proxy stateless: nessuno storage locale.
Best-effort: token assente/401/403/rete → vuoto/None, mai eccezione al chiamante."""
from __future__ import annotations

import base64
import json
import logging
import re
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session

from app.services.oauth_providers import get_valid_access_token

log = logging.getLogger(__name__)

_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _b64url_decode(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", "replace")
    except Exception:
        return ""


def parse_gmail_thread_id(url: str) -> Optional[str]:
    """Estrae il thread id da un URL Gmail. None se non riconosciuto/non-Gmail.
    Gestisce #inbox/ID, #label/Nome/ID, #search/query/ID e ?th=ID."""
    if not url or "mail.google.com" not in url:
        return None
    m = re.search(r"[?&]th=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)
    frag = url.split("#", 1)[1] if "#" in url else ""
    if frag:
        seg = frag.rstrip("/").split("/")[-1]
        if re.fullmatch(r"[A-Za-z0-9_-]{8,}", seg):
            return seg
    return None


def _gmail_request(method: str, path: str, token: str, params=None, body=None) -> dict:
    """Chiamata HTTP all'API Gmail. `path` relativo a /users/me. Punto unico di mock.
    Ritorna dict JSON (o {} se vuoto). Solleva su status >=400."""
    url = _API_BASE + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = None
    headers = {"Authorization": "Bearer " + token}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def _header(headers: list, name: str) -> str:
    for h in headers or []:
        if (h.get("name") or "").lower() == name.lower():
            return h.get("value") or ""
    return ""


def _walk_parts(payload: dict, acc: dict) -> None:
    mime = payload.get("mimeType") or ""
    body = payload.get("body") or {}
    filename = payload.get("filename") or ""
    att_id = body.get("attachmentId")
    if filename and att_id:
        acc["attachments"].append({
            "id": att_id, "filename": filename,
            "mime_type": mime or "application/octet-stream", "size": body.get("size") or 0})
        return
    data = body.get("data")
    if data:
        if mime == "text/html":
            acc["html"] += _b64url_decode(data)
        elif mime == "text/plain":
            acc["text"] += _b64url_decode(data)
    for p in payload.get("parts") or []:
        _walk_parts(p, acc)


def _normalize_message(msg: dict) -> dict:
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    acc = {"html": "", "text": "", "attachments": []}
    _walk_parts(payload, acc)
    return {
        "id": msg.get("id"), "thread_id": msg.get("threadId"),
        "from": _header(headers, "From"), "to": _header(headers, "To"),
        "cc": _header(headers, "Cc"), "subject": _header(headers, "Subject"),
        "date": _header(headers, "Date"), "snippet": msg.get("snippet") or "",
        "body_html": acc["html"], "body_text": acc["text"],
        "attachments": acc["attachments"],
    }


def list_threads(db: Session, user_id: int, *, query=None, label_ids=None,
                 page_token=None, max_results=25) -> dict:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return {"threads": [], "next_page_token": None}
    params = {"maxResults": max_results}
    if query:
        params["q"] = query
    if label_ids:
        params["labelIds"] = label_ids
    if page_token:
        params["pageToken"] = page_token
    try:
        res = _gmail_request("GET", "/threads", token, params=params) or {}
    except Exception as e:
        log.warning(f"list_threads fallita user={user_id}: {e}")
        return {"threads": [], "next_page_token": None}
    return {"threads": res.get("threads") or [], "next_page_token": res.get("nextPageToken")}


def get_thread(db: Session, user_id: int, thread_id: str) -> Optional[dict]:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    try:
        res = _gmail_request("GET", "/threads/" + urllib.parse.quote(thread_id), token,
                             params={"format": "full"}) or {}
    except Exception as e:
        log.warning(f"get_thread fallita user={user_id} thread={thread_id}: {e}")
        return None
    if not res:
        return None
    return {"id": res.get("id") or thread_id,
            "messages": [_normalize_message(m) for m in res.get("messages") or []]}


def list_labels(db: Session, user_id: int) -> list:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    try:
        res = _gmail_request("GET", "/labels", token) or {}
    except Exception as e:
        log.warning(f"list_labels fallita user={user_id}: {e}")
        return []
    return [{"id": l.get("id"), "name": l.get("name"), "type": l.get("type")}
            for l in res.get("labels") or []]


def build_mime(*, to, subject, body_html, cc=None, bcc=None,
               in_reply_to=None, references=None, attachments=None) -> str:
    """Costruisce un messaggio MIME e ritorna la stringa base64url (per Gmail 'raw')."""
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject or ""
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    # fallback testuale minimale + alternativa HTML
    msg.set_content("Questo messaggio richiede un client con supporto HTML.")
    msg.add_alternative(body_html or "", subtype="html")
    for att in attachments or []:
        maintype, _, subtype = (att.get("mime_type") or "application/octet-stream").partition("/")
        msg.add_attachment(att.get("data") or b"", maintype=maintype or "application",
                           subtype=subtype or "octet-stream", filename=att.get("filename") or "allegato")
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send_message(db: Session, user_id: int, *, to, subject, body_html, cc=None, bcc=None,
                 in_reply_to=None, references=None, thread_id=None, attachments=None) -> Optional[dict]:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    raw = build_mime(to=to, subject=subject, body_html=body_html, cc=cc, bcc=bcc,
                     in_reply_to=in_reply_to, references=references, attachments=attachments)
    body = {"raw": raw}
    if thread_id:
        body["threadId"] = thread_id
    try:
        return _gmail_request("POST", "/messages/send", token, body=body)
    except Exception as e:
        log.warning(f"send_message fallita user={user_id}: {e}")
        return None


def save_draft(db: Session, user_id: int, *, to, subject, body_html, cc=None, bcc=None,
               in_reply_to=None, references=None, thread_id=None, attachments=None) -> Optional[dict]:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    raw = build_mime(to=to, subject=subject, body_html=body_html, cc=cc, bcc=bcc,
                     in_reply_to=in_reply_to, references=references, attachments=attachments)
    message = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    try:
        return _gmail_request("POST", "/drafts", token, body={"message": message})
    except Exception as e:
        log.warning(f"save_draft fallita user={user_id}: {e}")
        return None


def list_drafts(db: Session, user_id: int) -> list:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    try:
        res = _gmail_request("GET", "/drafts", token) or {}
    except Exception as e:
        log.warning(f"list_drafts fallita user={user_id}: {e}")
        return []
    return res.get("drafts") or []


def delete_draft(db: Session, user_id: int, draft_id: str) -> bool:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    try:
        _gmail_request("DELETE", "/drafts/" + urllib.parse.quote(draft_id), token)
        return True
    except Exception as e:
        log.warning(f"delete_draft fallita user={user_id} draft={draft_id}: {e}")
        return False


def get_attachment(db: Session, user_id: int, message_id: str, attachment_id: str) -> Optional[bytes]:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    try:
        res = _gmail_request(
            "GET", "/messages/" + urllib.parse.quote(message_id) + "/attachments/" +
            urllib.parse.quote(attachment_id), token) or {}
    except Exception as e:
        log.warning(f"get_attachment fallita user={user_id} msg={message_id}: {e}")
        return None
    data = res.get("data")
    if not data:
        return None
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode())
    except Exception:
        return None
