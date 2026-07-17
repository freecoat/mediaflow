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
from concurrent.futures import ThreadPoolExecutor
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


from html import escape as _html_escape
from html.parser import HTMLParser

_ALLOWED_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li", "blockquote", "a"}
_ALLOWED_HREF_TAGS = {"a"}


def _safe_href(v: str) -> bool:
    s = (v or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("mailto:")


class _HtmlSanitizer(HTMLParser):
    """Allowlist sanitizer: tiene solo tag basilari, nessun attributo tranne
    href (http/https/mailto) su <a>. Testo escaped, script/style scartati.
    Difende da HTML AI-generato (prompt injection) verso innerHTML/invio."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
            return
        if tag not in _ALLOWED_TAGS:
            return
        if tag == "br":
            self.out.append("<br>")
            return
        kept = ""
        if tag in _ALLOWED_HREF_TAGS:
            for k, v in attrs:
                if k == "href" and v and _safe_href(v):
                    kept = ' href="%s"' % _html_escape(v, quote=True)
        self.out.append("<%s%s>" % (tag, kept))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            if self._skip:
                self._skip -= 1
            return
        if tag in _ALLOWED_TAGS and tag != "br":
            self.out.append("</%s>" % tag)

    def handle_data(self, data):
        if self._skip:
            return
        self.out.append(_html_escape(data))


def sanitize_html(html: str) -> str:
    """Ripulisce HTML non fidato lasciando solo tag/attributi in allowlist."""
    p = _HtmlSanitizer()
    try:
        p.feed(html or "")
        p.close()
    except Exception:
        return _html_escape(html or "")
    return "".join(p.out)


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
        # doseq: i parametri ripetuti (metadataHeaders, labelIds) sono liste e
        # senza doseq verrebbero stringificati come "['Subject', 'From']".
        url = url + "?" + urllib.parse.urlencode(params, doseq=True)
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


_THREAD_META_EMPTY = {"subject": "", "from": "", "date": "", "message_count": 0,
                      "msg_count": 0, "unread": False, "starred": False}


def _thread_headers(token: str, thread_id: str) -> dict:
    """Header del thread via fetch metadata (no corpo, no allegati).

    `users.threads.list` restituisce solo id/snippet/historyId: l'oggetto NON
    c'è. Va preso da `threads.get`, che è l'unico modo previsto dall'API Gmail.
    Come nella UI Gmail: oggetto = primo messaggio (il thread conserva quello
    originale), mittente/data = messaggio più recente.

    NON cattura le eccezioni: è il chiamante (`list_threads`) a fare il default,
    così l'invariante "le chiavi ci sono sempre" ha un punto solo di verità.
    `message_count`/`msg_count` sono lo stesso valore con due nomi: il primo lo
    legge il renderer di main, il secondo quello portato dal ramo."""
    res = _gmail_request("GET", "/threads/" + urllib.parse.quote(thread_id), token,
                         params={"format": "metadata",
                                 "metadataHeaders": ["Subject", "From", "Date"]}) or {}
    msgs = res.get("messages") or []
    if not msgs:
        return dict(_THREAD_META_EMPTY)
    first = (msgs[0].get("payload") or {}).get("headers") or []
    last = (msgs[-1].get("payload") or {}).get("headers") or []
    labels = set()
    for m in msgs:
        labels.update(m.get("labelIds") or [])
    return {"subject": _header(first, "Subject"), "from": _header(last, "From"),
            "date": _header(last, "Date"), "message_count": len(msgs),
            "msg_count": len(msgs),
            "unread": "UNREAD" in labels, "starred": "STARRED" in labels}


def list_threads(db: Session, user_id: int, *, query=None, label_ids=None,
                 page_token=None, max_results=25, enrich=True) -> dict:
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
    threads = [{"id": t.get("id"), "snippet": t.get("snippet") or ""}
               for t in res.get("threads") or []]
    if enrich and threads:
        # Gli header per-thread sono chiamate HTTP indipendenti: l'N+1 è il costo
        # previsto dall'API (threads.list non torna l'oggetto), ma sequenziale
        # significa 25 round-trip in fila (~5s). Il pool li collassa in pochi batch.
        def _safe(t):
            try:
                return _thread_headers(token, t["id"]) if t.get("id") else {}
            except Exception as e:
                # Best-effort: il thread resta in lista con oggetto ignoto, mai lo
                # snippet spacciato per oggetto.
                log.warning(f"metadata thread {t.get('id')} falliti user={user_id}: {e}")
                return {}

        with ThreadPoolExecutor(max_workers=min(8, len(threads))) as ex:
            metas = list(ex.map(_safe, threads))
        for t, meta in zip(threads, metas):
            # `or _THREAD_META_EMPTY`: le chiavi devono esserci SEMPRE, anche su
            # fallimento. Un `if meta:` qui lascerebbe la riga senza `subject`.
            t.update(meta or _THREAD_META_EMPTY)
    return {"threads": threads, "next_page_token": res.get("nextPageToken")}


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


def list_labels(db: Session, user_id: int, counts: bool = False) -> list:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    try:
        res = _gmail_request("GET", "/labels", token) or {}
    except Exception as e:
        log.warning(f"list_labels fallita user={user_id}: {e}")
        return []
    out = [{"id": l.get("id"), "name": l.get("name"), "type": l.get("type")}
           for l in res.get("labels") or []]
    if counts and out:
        def _count(lab):
            try:
                d = _gmail_request("GET", "/labels/" + urllib.parse.quote(lab["id"]), token) or {}
                return d.get("threadsUnread") or 0
            except Exception:
                return 0
        with ThreadPoolExecutor(max_workers=min(8, len(out))) as ex:
            vals = list(ex.map(_count, out))
        for lab, v in zip(out, vals):
            lab["threads_unread"] = v
    return out


# ── Etichette/cartelle CRUD (scope gmail.modify) — Sotto-fase 2b ───────

def create_label(db: Session, user_id: int, name: str, parent: str = None) -> Optional[dict]:
    """Crea un'etichetta utente. Se `parent`, la annida (`Parent/Nome`).
    Best-effort → dict {id,name,type} | None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    full = ((parent.rstrip("/") + "/") if parent else "") + (name or "").strip()
    if not full.strip("/"):
        return None
    body = {"name": full, "labelListVisibility": "labelShow",
            "messageListVisibility": "show"}
    try:
        res = _gmail_request("POST", "/labels", token, body=body) or {}
    except Exception as e:
        log.warning(f"create_label fallita user={user_id}: {e}")
        return None
    return {"id": res.get("id"), "name": res.get("name"), "type": res.get("type")}


def rename_label(db: Session, user_id: int, label_id: str, new_name: str) -> Optional[dict]:
    """Rinomina (o sposta annidando) un'etichetta. `new_name` è il nome pieno
    con eventuale `Parent/`. Best-effort → dict | None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token or not (new_name or "").strip():
        return None
    try:
        res = _gmail_request("PATCH", "/labels/" + urllib.parse.quote(label_id), token,
                             body={"name": new_name.strip()}) or {}
    except Exception as e:
        log.warning(f"rename_label fallita user={user_id} label={label_id}: {e}")
        return None
    return {"id": res.get("id"), "name": res.get("name"), "type": res.get("type")}


def delete_label(db: Session, user_id: int, label_id: str) -> bool:
    """Elimina un'etichetta utente. Best-effort → bool."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    try:
        _gmail_request("DELETE", "/labels/" + urllib.parse.quote(label_id), token)
        return True
    except Exception as e:
        log.warning(f"delete_label fallita user={user_id} label={label_id}: {e}")
        return False


# ── Filtri Gmail (scope gmail.settings.basic) — Sotto-fase 2d ──────────

def list_filters(db: Session, user_id: int) -> list:
    """Elenco filtri Gmail. Best-effort → [] su errore."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    try:
        res = _gmail_request("GET", "/settings/filters", token) or {}
    except Exception as e:
        log.warning(f"list_filters fallita user={user_id}: {e}")
        return []
    return res.get("filter") or []


def create_filter(db: Session, user_id: int, criteria: dict, action: dict) -> Optional[dict]:
    """Crea un filtro (criteria + action già pronti per l'API). Best-effort → dict|None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    crit = {k: v for k, v in (criteria or {}).items() if v not in (None, "", False, [])}
    act = {k: v for k, v in (action or {}).items() if v not in (None, "", [], {})}
    if not crit or not act:
        return None
    try:
        return _gmail_request("POST", "/settings/filters", token,
                              body={"criteria": crit, "action": act})
    except Exception as e:
        log.warning(f"create_filter fallita user={user_id}: {e}")
        return None


def delete_filter(db: Session, user_id: int, filter_id: str) -> bool:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    try:
        _gmail_request("DELETE", "/settings/filters/" + urllib.parse.quote(filter_id), token)
        return True
    except Exception as e:
        log.warning(f"delete_filter fallita user={user_id} filter={filter_id}: {e}")
        return False


# ── Risposta automatica / vacation responder (gmail.settings.basic) ────

def get_vacation(db: Session, user_id: int) -> dict:
    """Stato risposta automatica. Best-effort → {} su errore."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return {}
    try:
        return _gmail_request("GET", "/settings/vacation", token) or {}
    except Exception as e:
        log.warning(f"get_vacation fallita user={user_id}: {e}")
        return {}


def set_vacation(db: Session, user_id: int, *, enabled: bool, subject: str = "",
                 body_html: str = "", restrict_to_contacts: bool = False,
                 start_ms: int = None, end_ms: int = None) -> Optional[dict]:
    """Imposta/disattiva la risposta automatica. Best-effort → dict|None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    body = {"enableAutoReply": bool(enabled), "responseSubject": subject or "",
            "responseBodyHtml": body_html or "", "restrictToContacts": bool(restrict_to_contacts)}
    if start_ms:
        body["startTime"] = start_ms
    if end_ms:
        body["endTime"] = end_ms
    try:
        return _gmail_request("PUT", "/settings/vacation", token, body=body)
    except Exception as e:
        log.warning(f"set_vacation fallita user={user_id}: {e}")
        return None


# ── Azioni (Gmail-native, scope gmail.modify) — Sotto-fase 2a ──────────

def modify_thread(db: Session, user_id: int, thread_id: str,
                  add_labels=None, remove_labels=None) -> bool:
    """Aggiunge/rimuove etichette a un thread. Best-effort → bool."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    body = {"addLabelIds": add_labels or [], "removeLabelIds": remove_labels or []}
    try:
        _gmail_request("POST", "/threads/" + urllib.parse.quote(thread_id) + "/modify",
                       token, body=body)
        return True
    except Exception as e:
        log.warning(f"modify_thread fallita user={user_id} thread={thread_id}: {e}")
        return False


def _thread_simple(db: Session, user_id: int, thread_id: str, verb: str) -> bool:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    try:
        _gmail_request("POST", "/threads/" + urllib.parse.quote(thread_id) + "/" + verb, token)
        return True
    except Exception as e:
        log.warning(f"{verb} thread fallita user={user_id} thread={thread_id}: {e}")
        return False


def trash_thread(db: Session, user_id: int, thread_id: str) -> bool:
    return _thread_simple(db, user_id, thread_id, "trash")


def untrash_thread(db: Session, user_id: int, thread_id: str) -> bool:
    return _thread_simple(db, user_id, thread_id, "untrash")


# azione → (add_labels, remove_labels). label_id sostituisce il placeholder {LABEL}.
_ACTION_LABELS = {
    "read": ([], ["UNREAD"]),
    "unread": (["UNREAD"], []),
    "star": (["STARRED"], []),
    "unstar": ([], ["STARRED"]),
    "archive": ([], ["INBOX"]),
    "spam": (["SPAM"], ["INBOX"]),
    "move": (["{LABEL}"], ["INBOX"]),
    "label": (["{LABEL}"], []),
    "unlabel": ([], ["{LABEL}"]),
}


def apply_action(db: Session, user_id: int, thread_ids, action: str,
                 label_id=None) -> dict:
    """Applica un'azione a uno o più thread. Ritorna {ok, failed}."""
    ids = [t for t in (thread_ids or []) if t]
    ok, failed = 0, 0
    for tid in ids:
        if action in ("trash", "untrash"):
            res = _thread_simple(db, user_id, tid, action)
        elif action in _ACTION_LABELS:
            add, rem = _ACTION_LABELS[action]
            add = [label_id if x == "{LABEL}" else x for x in add]
            rem = [label_id if x == "{LABEL}" else x for x in rem]
            if any(x is None for x in add + rem):  # label_id mancante
                res = False
            else:
                res = modify_thread(db, user_id, tid, add_labels=add, remove_labels=rem)
        else:
            res = False
        if res:
            ok += 1
        else:
            failed += 1
    return {"ok": ok, "failed": failed}


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


def update_draft(db: Session, user_id: int, draft_id: str, *, to, subject, body_html,
                 cc=None, bcc=None, in_reply_to=None, references=None,
                 thread_id=None, attachments=None) -> Optional[dict]:
    """Aggiorna una bozza esistente (autosave). Best-effort → dict|None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    raw = build_mime(to=to, subject=subject, body_html=body_html, cc=cc, bcc=bcc,
                     in_reply_to=in_reply_to, references=references, attachments=attachments)
    message = {"raw": raw}
    if thread_id:
        message["threadId"] = thread_id
    try:
        return _gmail_request("PUT", "/drafts/" + urllib.parse.quote(draft_id), token,
                              body={"id": draft_id, "message": message})
    except Exception as e:
        log.warning(f"update_draft fallita user={user_id} draft={draft_id}: {e}")
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


_PEOPLE_BASE = "https://people.googleapis.com/v1"


def _people_request(path: str, token: str, params=None) -> dict:
    """GET su People API (base diversa da Gmail). Punto di mock separato."""
    url = _PEOPLE_BASE + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, method="GET",
                                 headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def _collect_people(people: list, out: dict) -> None:
    for p in people or []:
        name = ((p.get("names") or [{}])[0]).get("displayName") or ""
        for em in p.get("emailAddresses") or []:
            e = (em.get("value") or "").strip()
            if e and e.lower() not in out:
                out[e.lower()] = {"email": e, "name": name}


def list_contacts(db: Session, user_id: int, limit: int = 800) -> list:
    """Rubrica per autocomplete: contatti Google (connections) + contatti
    auto-salvati dalle email (otherContacts). Best-effort: errore → lista parziale/[]."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    out: dict = {}
    try:
        res = _people_request("/people/me/connections", token,
                              params={"personFields": "names,emailAddresses", "pageSize": 1000})
        _collect_people(res.get("connections"), out)
    except Exception as e:
        log.warning(f"connections fallita user={user_id}: {e}")
    try:
        res = _people_request("/otherContacts", token,
                              params={"readMask": "names,emailAddresses", "pageSize": 1000})
        _collect_people(res.get("otherContacts"), out)
    except Exception as e:
        log.warning(f"otherContacts fallita user={user_id}: {e}")
    return list(out.values())[:limit]


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
