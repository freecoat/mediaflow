# Client Email — Sotto-fase 1: `/mail` webmail standalone — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pagina `/mail` = client webmail standalone su Gmail (leggi + cerca + conversazione + compose/invia/reply/forward + allegati + bozze), con opt-in Gmail incrementale e rendering corpo email in iframe sandboxed.

**Architecture:** Layer HTTP isolato `app/services/gmail.py` (urllib, unico `_gmail_request` mockabile, best-effort) sopra l'OAuth esistente (Fase A). Scope Gmail (`gmail.readonly` + `gmail.compose`) richiesti via **autorizzazione incrementale opt-in** (`include_granted_scopes=true`), NON nel bundle di default. Router `app/routers/mail.py` = proxy stateless verso Gmail (nessuna tabella/migrazione). Frontend `mail.html`+`mail.js` a 3 pannelli con compose modal. Corpo HTML reso in iframe `sandbox=""` + immagini remote bloccate di default.

**Tech Stack:** FastAPI, urllib.request, email.message.EmailMessage (stdlib), Gmail API v1 REST, Jinja2, vanilla JS, i18n client-side.

## Global Constraints

- **Ramo:** `feat/mail-client-phase1`. Nessun push finché Matteo non fa smoke.
- **Nessuna nuova dipendenza Python.** HTTP via `urllib.request`; MIME via `email.message.EmailMessage` (stdlib). Unico `_gmail_request` = punto di mock.
- **Token:** `get_valid_access_token(db, user_id, "google") -> Optional[str]` (auto-refresh, non committa) e `get_token(db, user_id, "google") -> Optional[UserOAuthToken]` da `app.services.oauth_providers`.
- **Scope opt-in:** `gmail.readonly` + `gmail.compose` richiesti SOLO su azione esplicita (`/auth/oauth/google/start?scopes=email`), con `include_granted_scopes=true`. NON aggiungere questi scope al bundle di default in `PROVIDERS`. `UserOAuthToken.scopes` (già salvato dal callback) è la fonte di verità per "email abilitata".
- **Stateless:** `/mail` non ha storage locale né migrazioni. Contenuto per-utente (non tenant-scoped): auth via `current_user(request)` (401 se assente), da `app.services.rbac`.
- **Best-effort:** token assente / 401 / 403 / rete → ritorno vuoto/`None`, mai eccezione propagata al render (pattern Fase C/D). Mai 500 su chiamata Gmail fallita.
- **Sicurezza:** corpo email in iframe `sandbox=""` (no `allow-scripts`) via `srcdoc`; immagini remote bloccate di default (toggle per-messaggio); invio con conferma esplicita; mai refresh token al client; nessun token nei log; allegati `Content-Disposition: attachment`.
- **Form-based** per scrittura (`Form(...)`), **i18n 5 lingue** (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`, **cache-buster** `?v={app_version}` su JS nuovo. Helper globali (`escapeHtml`,`api`,`toast`,`mfT`) da `global.js`, non ridefiniti. No `JSON.stringify` in onclick → `data-*`. `mfT(key)` 1-arg (chiavi sempre definite).
- **Base64url:** decode con padding `data + "=" * (-len(data) % 4)` poi `base64.urlsafe_b64decode`; encode con `base64.urlsafe_b64encode(...).decode()`.
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (heredoc bloccato da hook; usare `printf` in bash, non PowerShell, per evitare BOM).
- **Versione:** `3.5.0-alpha.172.243` → `.244` (Task 7).
- **Smoke server:** uvicorn SENZA reload: `.venv/Scripts/python.exe -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, log_level='warning')"`. `127.0.0.1`, NON `APP_ENV=production`.

---

### Task 1: Opt-in Gmail — scope incrementali

Aggiunge la richiesta scope Gmail come autorizzazione incrementale opt-in, senza toccare il bundle di default.

**Files:**
- Modify: `app/services/oauth_providers.py` (costante `GMAIL_SCOPES` + param `extra_scopes` in `authorization_url`)
- Modify: `app/routers/oauth.py` (`oauth_start` accetta `?scopes=email`)
- Test: `tests/test_oauth_gmail_optin.py`

**Interfaces:**
- Produces:
  - `oauth_providers.GMAIL_SCOPES: str` = `"https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose"`.
  - `authorization_url(provider: str, state: str, extra_scopes: Optional[str] = None) -> str` — se `extra_scopes` dato, li appende agli scope base e aggiunge `include_granted_scopes=true`.
  - `GET /auth/oauth/google/start?scopes=email` → redirect all'auth URL con scope base + Gmail.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_oauth_gmail_optin.py
import urllib.parse
from app.services import oauth_providers as oauth


def _params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_gmail_scopes_constant():
    assert "gmail.readonly" in oauth.GMAIL_SCOPES
    assert "gmail.compose" in oauth.GMAIL_SCOPES


def test_authorization_url_default_no_gmail_read():
    url = oauth.authorization_url("google", "st")
    scope = _params(url)["scope"]
    assert "gmail.readonly" not in scope          # opt-in: non nel bundle di default
    assert "include_granted_scopes" not in _params(url)


def test_authorization_url_with_extra_scopes():
    url = oauth.authorization_url("google", "st", extra_scopes=oauth.GMAIL_SCOPES)
    p = _params(url)
    assert "gmail.readonly" in p["scope"]
    assert "gmail.compose" in p["scope"]
    assert p["include_granted_scopes"] == "true"
    # gli scope base restano presenti
    assert "calendar.app.created" in p["scope"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_oauth_gmail_optin.py -v`
Expected: FAIL (`AttributeError: GMAIL_SCOPES` / `authorization_url()` non accetta `extra_scopes`).

- [ ] **Step 3: Add GMAIL_SCOPES + extra_scopes param**

In `app/services/oauth_providers.py`, dopo il dict `PROVIDERS` (dopo riga ~71):

```python
# Scope Gmail richiesti SOLO su opt-in email (autorizzazione incrementale).
# NON inseriti nel bundle PROVIDERS["google"]["scopes"] di default.
GMAIL_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/gmail.compose"
)
```

Sostituisci la funzione `authorization_url` (riga ~126) con:

```python
def authorization_url(provider: str, state: str, extra_scopes: Optional[str] = None) -> str:
    """Costruisce URL di autorizzazione del provider.
    Se extra_scopes è dato, li appende agli scope base e richiede
    include_granted_scopes=true (autorizzazione incrementale)."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Provider OAuth sconosciuto: {provider}")
    scope = cfg["scopes"]
    if extra_scopes:
        scope = scope + " " + extra_scopes
    params = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": scope,
        "state": state,
        "access_type": "offline",      # Google: forza refresh_token
        "prompt": "consent",            # Forza re-consent per ottenere refresh_token
    }
    if extra_scopes:
        params["include_granted_scopes"] = "true"
    return cfg["auth_url"] + "?" + urllib.parse.urlencode(params)
```

- [ ] **Step 4: Wire opt-in into oauth_start**

In `app/routers/oauth.py`, sostituisci la firma e il corpo di `oauth_start` (riga ~52-67):

```python
@router.get("/{provider}/start")
async def oauth_start(provider: str, request: Request, scopes: Optional[str] = None,
                      db: Session = Depends(get_db)):
    """Inizio flow OAuth: genera state CSRF + redirect a auth URL.
    `scopes=email` richiede in aggiunta gli scope Gmail (opt-in incrementale)."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta")
    if provider not in oauth.PROVIDERS:
        raise HTTPException(404, f"Provider OAuth sconosciuto: {provider}")
    if not oauth.is_configured(provider):
        raise HTTPException(
            503,
            f"Provider {provider} non configurato (manca {oauth.PROVIDERS[provider]['client_id_env']} "
            f"o {oauth.PROVIDERS[provider]['client_secret_env']} in .env). "
            "Contatta amministratore.")
    extra = oauth.GMAIL_SCOPES if (provider == "google" and scopes == "email") else None
    state = oauth.make_oauth_state(user.id, provider)
    return RedirectResponse(oauth.authorization_url(provider, state, extra_scopes=extra))
```

Verifica che `Optional` sia importato in `oauth.py` (lo è: usato in `oauth_callback`).

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_oauth_gmail_optin.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add app/services/oauth_providers.py app/routers/oauth.py tests/test_oauth_gmail_optin.py
git commit -F <msgfile>
# "feat(mail): opt-in Gmail scope incrementali (readonly+compose)"
```

---

### Task 2: `gmail.py` — lettura (threads, thread normalizzato, labels)

**Files:**
- Create: `app/services/gmail.py`
- Test: `tests/test_gmail_read.py`

**Interfaces:**
- Consumes: `get_valid_access_token` (oauth_providers).
- Produces:
  - `_gmail_request(method, path, token, params=None, body=None) -> dict` (mock point; `path` relativo a `/users/me`).
  - `list_threads(db, user_id, *, query=None, label_ids=None, page_token=None, max_results=25) -> dict` → `{"threads": [...], "next_page_token": Optional[str]}` (best-effort → `{"threads": [], "next_page_token": None}`).
  - `get_thread(db, user_id, thread_id) -> Optional[dict]` → `{"id", "messages": [ _normalize_message(...) ]}` o `None`.
  - `_normalize_message(msg: dict) -> dict` → `{id, thread_id, from, to, cc, subject, date, snippet, body_html, body_text, attachments:[{id, filename, mime_type, size}]}`.
  - `list_labels(db, user_id) -> list[dict]` → `[{"id","name","type"}]` (best-effort → `[]`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gmail_read.py
import base64
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
from datetime import timedelta
from app.services import gmail


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, is_active=True))
    s.commit()
    return s


def _connect(s):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         scopes="https://www.googleapis.com/auth/gmail.readonly",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def test_list_threads_ok(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "threads": [{"id": "T1", "snippet": "ciao"}], "nextPageToken": "NXT"})
    out = gmail.list_threads(s, 1, query="from:x@y.com")
    assert out["threads"][0]["id"] == "T1"
    assert out["next_page_token"] == "NXT"


def test_list_threads_best_effort_without_token():
    s = _session()  # nessun token
    assert gmail.list_threads(s, 1) == {"threads": [], "next_page_token": None}


def test_get_thread_normalizes(monkeypatch):
    s = _session(); _connect(s)
    payload = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "From", "value": "Mitt <m@x.com>"},
                    {"name": "To", "value": "me@t.local"},
                    {"name": "Subject", "value": "Oggetto"},
                    {"name": "Date", "value": "Mon, 7 Jul 2026 10:00:00 +0000"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("testo puro")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
            {"mimeType": "application/pdf", "filename": "a.pdf",
             "body": {"attachmentId": "ATT1", "size": 1234}},
        ],
    }
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "id": "T1", "messages": [{"id": "M1", "threadId": "T1", "snippet": "s", "payload": payload}]})
    thr = gmail.get_thread(s, 1, "T1")
    msg = thr["messages"][0]
    assert msg["from"] == "Mitt <m@x.com>"
    assert msg["subject"] == "Oggetto"
    assert msg["body_html"] == "<p>html</p>"
    assert msg["body_text"] == "testo puro"
    assert msg["attachments"][0] == {"id": "ATT1", "filename": "a.pdf",
                                     "mime_type": "application/pdf", "size": 1234}


def test_get_thread_best_effort_on_error(monkeypatch):
    s = _session(); _connect(s)
    def boom(*a, **k): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.get_thread(s, 1, "T1") is None


def test_list_labels_ok(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "labels": [{"id": "INBOX", "name": "INBOX", "type": "system"},
                   {"id": "Label_1", "name": "Clienti", "type": "user"}]})
    labs = gmail.list_labels(s, 1)
    assert {"id": "INBOX", "name": "INBOX", "type": "system"} in labs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_read.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.gmail`).

- [ ] **Step 3: Create `gmail.py` (parte lettura)**

```python
# app/services/gmail.py
"""Gmail API client — Client email Sotto-fase 1 (v3.5.0-alpha.172.244).

Layer HTTP isolato (urllib, coerente con google_drive.py/google_calendar.py).
Unico `_gmail_request` = punto di mock. Proxy stateless: nessuno storage locale.
Best-effort: token assente/401/403/rete → vuoto/None, mai eccezione al chiamante."""
from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import urllib.request
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_read.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/gmail.py tests/test_gmail_read.py
git commit -F <msgfile>
# "feat(mail): gmail.py lettura — threads/thread normalizzato/labels"
```

---

### Task 3: `gmail.py` — invio (MIME build), bozze, allegati

**Files:**
- Modify: `app/services/gmail.py` (aggiunge send/draft/attachment in fondo)
- Test: `tests/test_gmail_send.py`

**Interfaces:**
- Consumes: `_gmail_request`, `get_valid_access_token` (Task 2).
- Produces:
  - `build_mime(*, to, subject, body_html, cc=None, bcc=None, in_reply_to=None, references=None, attachments=None) -> str` → stringa base64url del messaggio MIME. `attachments` = `[{"filename","mime_type","data"(bytes)}]`.
  - `send_message(db, user_id, *, to, subject, body_html, cc=None, bcc=None, in_reply_to=None, references=None, thread_id=None, attachments=None) -> Optional[dict]` → risposta Gmail (`{"id","threadId",...}`) o `None` best-effort.
  - `save_draft(db, user_id, **kwargs) -> Optional[dict]`, `list_drafts(db, user_id) -> list`, `delete_draft(db, user_id, draft_id) -> bool`.
  - `get_attachment(db, user_id, message_id, attachment_id) -> Optional[bytes]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gmail_send.py
import base64
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
from app.services import gmail


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, is_active=True))
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         scopes="https://www.googleapis.com/auth/gmail.compose",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()
    return s


def _decode_raw(raw_b64):
    return base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4)).decode("utf-8", "replace")


def test_build_mime_basic():
    raw = gmail.build_mime(to="x@y.com", subject="Ciao", body_html="<p>hi</p>")
    txt = _decode_raw(raw)
    assert "To: x@y.com" in txt
    assert "Subject: Ciao" in txt
    assert "hi" in txt


def test_build_mime_reply_headers():
    raw = gmail.build_mime(to="x@y.com", subject="Re: Ciao", body_html="<p>r</p>",
                           in_reply_to="<abc@mail>", references="<abc@mail>")
    txt = _decode_raw(raw)
    assert "In-Reply-To: <abc@mail>" in txt
    assert "References: <abc@mail>" in txt


def test_build_mime_attachment():
    raw = gmail.build_mime(to="x@y.com", subject="A", body_html="<p>a</p>",
                           attachments=[{"filename": "n.txt", "mime_type": "text/plain",
                                         "data": b"hello"}])
    txt = _decode_raw(raw)
    assert "n.txt" in txt


def test_send_message_passes_thread_id(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["path"] = p; captured["body"] = body
        return {"id": "SENT1", "threadId": "T9"}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.send_message(s, 1, to="x@y.com", subject="S", body_html="<p>b</p>", thread_id="T9")
    assert out["id"] == "SENT1"
    assert captured["path"] == "/messages/send"
    assert captured["body"]["threadId"] == "T9"
    assert "raw" in captured["body"]


def test_send_message_best_effort_on_error(monkeypatch):
    s = _session()
    def boom(*a, **k): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.send_message(s, 1, to="x@y.com", subject="S", body_html="b") is None


def test_get_attachment_decodes(monkeypatch):
    s = _session()
    payload = base64.urlsafe_b64encode(b"filedata").rstrip(b"=").decode()
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "data": payload, "size": 8})
    assert gmail.get_attachment(s, 1, "M1", "ATT1") == b"filedata"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_send.py -v`
Expected: FAIL (`AttributeError: build_mime`).

- [ ] **Step 3: Append invio/bozze/allegati a `gmail.py`**

In fondo a `app/services/gmail.py` aggiungi:

```python
import base64 as _b64mod  # già importato base64 in cima; alias non necessario, usa base64
from email.message import EmailMessage


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
```

Nota: rimuovi la riga `import base64 as _b64mod` se lasciata (era solo un promemoria); `base64` è già importato in cima e `from email.message import EmailMessage` va spostato tra gli import in cima al file per pulizia. L'implementatore consolidi gli import in testa.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_send.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/gmail.py tests/test_gmail_send.py
git commit -F <msgfile>
# "feat(mail): gmail.py invio MIME + bozze + allegati"
```

---

### Task 4: Router `mail.py` — lettura (status/threads/thread/labels/attachment) + registrazione

**Files:**
- Create: `app/routers/mail.py`
- Modify: `app/main.py` (import + `include_router`, vicino a `documents_router`)
- Test: `tests/test_mail_api_read.py`

**Interfaces:**
- Consumes: `gmail` service (Task 2/3); `current_user` (rbac); `get_token` (oauth_providers).
- Produces:
  - `GET /mail` → HTML `mail.html`.
  - `GET /mail/api/status` → `{"connected": bool, "account_email": Optional[str]}` (connected = token con scope `gmail.readonly`).
  - `GET /mail/api/threads?label&q&page_token` → `{"threads":[...], "next_page_token":...}`.
  - `GET /mail/api/thread/{thread_id}` → thread normalizzato o 404.
  - `GET /mail/api/labels` → `{"labels":[...]}`.
  - `GET /mail/api/attachment/{message_id}/{attachment_id}?filename=&mime=` → bytes con `Content-Disposition: attachment`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mail_api_read.py
import pytest
from fastapi.testclient import TestClient
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import get_db
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc


@pytest.fixture
def client(monkeypatch):
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    TS = sessionmaker(bind=e, expire_on_commit=False, future=True)
    s = TS()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    u = User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
             hashed_password="x", role=UserRole.admin, is_active=True)
    s.add(u); s.commit()

    def _get_db():
        try:
            yield s
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod, "current_user", lambda request=None: u)
    c = TestClient(app)
    yield c, s, monkeypatch, mailmod
    app.dependency_overrides.clear()


def test_status_disconnected(client):
    c, s, mp, mailmod = client
    r = c.get("/mail/api/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_status_connected(client):
    c, s, mp, mailmod = client
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         account_email="admin@gmail.com",
                         scopes="https://www.googleapis.com/auth/gmail.readonly",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()
    r = c.get("/mail/api/status")
    b = r.json()
    assert b["connected"] is True
    assert b["account_email"] == "admin@gmail.com"


def test_threads(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "list_threads",
               lambda db, uid, **k: {"threads": [{"id": "T1", "snippet": "x"}], "next_page_token": None})
    r = c.get("/mail/api/threads", params={"label": "INBOX"})
    assert r.status_code == 200
    assert r.json()["threads"][0]["id"] == "T1"


def test_thread_404(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "get_thread", lambda db, uid, tid: None)
    assert c.get("/mail/api/thread/NOPE").status_code == 404


def test_thread_ok(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "get_thread",
               lambda db, uid, tid: {"id": tid, "messages": [{"id": "M1", "subject": "S"}]})
    r = c.get("/mail/api/thread/T1")
    assert r.json()["messages"][0]["subject"] == "S"


def test_labels(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "list_labels",
               lambda db, uid: [{"id": "INBOX", "name": "INBOX", "type": "system"}])
    r = c.get("/mail/api/labels")
    assert r.json()["labels"][0]["id"] == "INBOX"


def test_attachment_download(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "get_attachment", lambda db, uid, mid, aid: b"filebytes")
    r = c.get("/mail/api/attachment/M1/ATT1", params={"filename": "a.txt", "mime": "text/plain"})
    assert r.status_code == 200
    assert r.content == b"filebytes"
    assert "attachment" in r.headers.get("content-disposition", "")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_api_read.py -v`
Expected: FAIL (404 su tutti gli endpoint — router assente).

- [ ] **Step 3: Create `mail.py` (lettura)**

```python
# app/routers/mail.py
"""Router client email — Client email Sotto-fase 1 (v3.5.0-alpha.172.244).

Pagina /mail = webmail standalone su Gmail. Proxy stateless (nessuno storage
locale). Contenuto per-utente (non tenant-scoped). Best-effort: chiamate Gmail
fallite → risposta vuota, mai 500."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.templates_config import templates  # vedi nota sotto
from app.services.rbac import current_user
from app.services.oauth_providers import get_token
from app.services import gmail

router = APIRouter(tags=["mail"])

_GMAIL_READ_SCOPE = "gmail.readonly"


@router.get("/mail")
async def mail_page(request: Request):
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
```

Nota import `templates`: usa lo stesso oggetto Jinja degli altri router. Verifica come `calendar.py`/`documents.py` importano `templates` (probabilmente `from app.main import templates` o un modulo dedicato) e **replica esattamente quell'import** — sostituisci `from app.templates_config import templates` con il pattern reale del progetto.

- [ ] **Step 4: Register in `main.py`**

In `app/main.py`, con gli altri import router:
```python
from app.routers import mail as mail_router
```
Dopo `app.include_router(documents_router.router)`:
```python
app.include_router(mail_router.router)  # Client email Sotto-fase 1 — /mail
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_api_read.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add app/routers/mail.py app/main.py tests/test_mail_api_read.py
git commit -F <msgfile>
# "feat(mail): router lettura /mail (status/threads/thread/labels/attachment)"
```

---

### Task 5: Router `mail.py` — invio + bozze

**Files:**
- Modify: `app/routers/mail.py` (endpoint send/draft)
- Test: `tests/test_mail_api_send.py`

**Interfaces:**
- Consumes: `gmail.send_message`, `gmail.save_draft`, `gmail.list_drafts`, `gmail.delete_draft`.
- Produces:
  - `POST /mail/api/send` (Form: `to`,`subject`,`body`, opz `cc`,`bcc`,`thread_id`,`in_reply_to`,`references`; opz file `attachments`) → `{"ok":bool,"id":...}`.
  - `POST /mail/api/draft` (stessi campi) → draft creato.
  - `GET /mail/api/drafts` → `{"drafts":[...]}`.
  - `DELETE /mail/api/draft/{draft_id}` → `{"ok":bool}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mail_api_send.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import get_db
from app.models.models import Base, Tenant, User, UserRole


@pytest.fixture
def client(monkeypatch):
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    u = User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
             hashed_password="x", role=UserRole.admin, is_active=True)
    s.add(u); s.commit()

    def _get_db():
        try:
            yield s
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod, "current_user", lambda request=None: u)
    c = TestClient(app)
    yield c, s, monkeypatch, mailmod
    app.dependency_overrides.clear()


def test_send_ok(client):
    c, s, mp, mailmod = client
    captured = {}
    def fake_send(db, uid, **k):
        captured.update(k); return {"id": "SENT1", "threadId": "T1"}
    mp.setattr(mailmod.gmail, "send_message", fake_send)
    r = c.post("/mail/api/send", data={"to": "x@y.com", "subject": "S", "body": "<p>b</p>",
                                       "thread_id": "T1", "in_reply_to": "<a@m>"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert captured["to"] == "x@y.com"
    assert captured["thread_id"] == "T1"
    assert captured["in_reply_to"] == "<a@m>"


def test_send_failure_returns_ok_false(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "send_message", lambda db, uid, **k: None)
    r = c.post("/mail/api/send", data={"to": "x@y.com", "subject": "S", "body": "b"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_send_with_attachment(client):
    c, s, mp, mailmod = client
    captured = {}
    def fake_send(db, uid, **k):
        captured.update(k); return {"id": "S2"}
    mp.setattr(mailmod.gmail, "send_message", fake_send)
    r = c.post("/mail/api/send", data={"to": "x@y.com", "subject": "S", "body": "b"},
               files={"attachments": ("n.txt", b"hello", "text/plain")})
    assert r.status_code == 200
    assert captured["attachments"][0]["filename"] == "n.txt"
    assert captured["attachments"][0]["data"] == b"hello"


def test_draft_create(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "save_draft", lambda db, uid, **k: {"id": "D1"})
    r = c.post("/mail/api/draft", data={"to": "x@y.com", "subject": "S", "body": "b"})
    assert r.status_code == 200
    assert r.json()["id"] == "D1"


def test_draft_delete(client):
    c, s, mp, mailmod = client
    mp.setattr(mailmod.gmail, "delete_draft", lambda db, uid, did: True)
    r = c.delete("/mail/api/draft/D1")
    assert r.json()["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_api_send.py -v`
Expected: FAIL (404 send/draft).

- [ ] **Step 3: Append send/draft a `mail.py`**

Aggiungi in cima agli import di `app/routers/mail.py`: `from fastapi import Form, UploadFile, File` (accanto agli import fastapi esistenti) e `from typing import List`. Poi in fondo al file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_api_send.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/routers/mail.py tests/test_mail_api_send.py
git commit -F <msgfile>
# "feat(mail): router invio + bozze /mail"
```

---

### Task 6: Frontend `mail.html` + `mail.js` + i18n + sidebar + settings opt-in

**Files:**
- Create: `app/templates/pages/mail.html`
- Create: `app/static/js/mail.js`
- Modify: `app/static/js/i18n.js` (chiavi `mail.*` + `nav.mail`)
- Modify: `app/templates/base.html` (voce sidebar Email, dopo la voce Calendar riga ~85)
- Modify: la card Google in `/settings` (bottone "Abilita Email" → `/auth/oauth/google/start?scopes=email`; individua il template della card Account — riga con connect Google)
- Test: `tests/test_mail_page.py`

**Interfaces:**
- Consumes: endpoint Task 4/5; helper globali `escapeHtml`,`toast`,`mfT`,`api`.
- Produces: pagina 3-pannelli + compose modal; funzioni globali `mfMailInit`, `mfMailLoadThreads`, `mfMailOpenThread`, `mfMailCompose`, `mfMailSend`. Corpo email in iframe `sandbox=""`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mail_page.py
import pathlib


def test_mail_html_panes():
    html = pathlib.Path("app/templates/pages/mail.html").read_text(encoding="utf-8")
    assert 'id="mail-labels"' in html
    assert 'id="mail-thread-list"' in html
    assert 'id="mail-reading"' in html
    assert 'mail.js' in html


def test_mail_js_globals_and_sandbox():
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    for fn in ("mfMailInit", "mfMailLoadThreads", "mfMailOpenThread", "mfMailCompose", "mfMailSend"):
        assert fn in src, fn
    assert "sandbox" in src            # corpo email in iframe sandboxed
    assert "srcdoc" in src


def test_i18n_mail_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("nav.mail", "mail.inbox", "mail.compose", "mail.send", "mail.reply",
                "mail.replyAll", "mail.forward", "mail.search", "mail.notConnected",
                "mail.connect", "mail.showImages", "mail.sent", "mail.sendError"):
        assert key in src, key


def test_sidebar_has_mail():
    html = pathlib.Path("app/templates/base.html").read_text(encoding="utf-8")
    assert '/mail' in html
    assert 'data-i18n="nav.mail"' in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_page.py -v`
Expected: FAIL (file/chiavi assenti).

- [ ] **Step 3: Add i18n keys**

In `app/static/js/i18n.js`, vicino alle chiavi `nav.*` aggiungi `'nav.mail'` e (vicino alle `doc.*`/`cal.*`) il blocco `mail.*`:

```javascript
  'nav.mail':          {it: 'Email', en: 'Email', fr: 'E-mail', de: 'E-Mail', es: 'Correo'},
  'mail.inbox':        {it: 'Posta in arrivo', en: 'Inbox', fr: 'Boîte de réception', de: 'Posteingang', es: 'Bandeja de entrada'},
  'mail.sent':         {it: 'Inviati', en: 'Sent', fr: 'Envoyés', de: 'Gesendet', es: 'Enviados'},
  'mail.drafts':       {it: 'Bozze', en: 'Drafts', fr: 'Brouillons', de: 'Entwürfe', es: 'Borradores'},
  'mail.compose':      {it: 'Scrivi', en: 'Compose', fr: 'Nouveau', de: 'Schreiben', es: 'Redactar'},
  'mail.send':         {it: 'Invia', en: 'Send', fr: 'Envoyer', de: 'Senden', es: 'Enviar'},
  'mail.reply':        {it: 'Rispondi', en: 'Reply', fr: 'Répondre', de: 'Antworten', es: 'Responder'},
  'mail.replyAll':     {it: 'Rispondi a tutti', en: 'Reply all', fr: 'Répondre à tous', de: 'Allen antworten', es: 'Responder a todos'},
  'mail.forward':      {it: 'Inoltra', en: 'Forward', fr: 'Transférer', de: 'Weiterleiten', es: 'Reenviar'},
  'mail.search':       {it: 'Cerca nella posta…', en: 'Search mail…', fr: 'Rechercher…', de: 'E-Mail suchen…', es: 'Buscar correo…'},
  'mail.to':           {it: 'A', en: 'To', fr: 'À', de: 'An', es: 'Para'},
  'mail.subject':      {it: 'Oggetto', en: 'Subject', fr: 'Objet', de: 'Betreff', es: 'Asunto'},
  'mail.saveDraft':    {it: 'Salva bozza', en: 'Save draft', fr: 'Enregistrer', de: 'Entwurf speichern', es: 'Guardar borrador'},
  'mail.attach':       {it: 'Allega', en: 'Attach', fr: 'Joindre', de: 'Anhängen', es: 'Adjuntar'},
  'mail.notConnected': {it: 'Collega Gmail per usare la posta', en: 'Connect Gmail to use mail', fr: 'Connectez Gmail', de: 'Gmail verbinden', es: 'Conecta Gmail'},
  'mail.connect':      {it: 'Collega Gmail', en: 'Connect Gmail', fr: 'Connecter Gmail', de: 'Gmail verbinden', es: 'Conectar Gmail'},
  'mail.showImages':   {it: 'Mostra immagini', en: 'Show images', fr: 'Afficher les images', de: 'Bilder anzeigen', es: 'Mostrar imágenes'},
  'mail.empty':        {it: 'Nessun messaggio', en: 'No messages', fr: 'Aucun message', de: 'Keine Nachrichten', es: 'Sin mensajes'},
  'mail.sendConfirm':  {it: 'Inviare questa email?', en: 'Send this email?', fr: 'Envoyer cet e-mail ?', de: 'Diese E-Mail senden?', es: '¿Enviar este correo?'},
  'mail.sentOk':       {it: 'Email inviata', en: 'Email sent', fr: 'E-mail envoyé', de: 'E-Mail gesendet', es: 'Correo enviado'},
  'mail.sendError':    {it: 'Invio fallito', en: 'Send failed', fr: 'Échec de l’envoi', de: 'Senden fehlgeschlagen', es: 'Error al enviar'},
  'mail.loadMore':     {it: 'Carica altri', en: 'Load more', fr: 'Charger plus', de: 'Mehr laden', es: 'Cargar más'},
```

(La chiave `mail.sent` è usata sia come label cartella sia coperta dal test; `mail.sentOk` per il toast di conferma invio. Il test cerca `mail.sent` e `mail.sendError` — entrambe presenti.)

- [ ] **Step 4: Create `mail.js`**

```javascript
// app/static/js/mail.js — Client email Sotto-fase 1: webmail /mail
let _mailLabel = 'INBOX';
let _mailNextPage = null;
let _mailConnected = false;

async function mfMailInit() {
  const st = await (await fetch('/mail/api/status')).json().catch(function () { return {connected: false}; });
  _mailConnected = !!st.connected;
  if (!_mailConnected) {
    const box = document.getElementById('mail-reading');
    if (box) box.innerHTML = '<div class="mail-cta"><p>' + mfT('mail.notConnected') +
      '</p><a class="btn btn-primary" href="/auth/oauth/google/start?scopes=email">' +
      mfT('mail.connect') + '</a></div>';
    return;
  }
  mfMailLoadLabels();
  mfMailLoadThreads(true);
}

async function mfMailLoadLabels() {
  try {
    const d = await (await fetch('/mail/api/labels')).json();
    const box = document.getElementById('mail-labels');
    if (!box) return;
    const sys = [['INBOX', mfT('mail.inbox')], ['SENT', mfT('mail.sent')], ['DRAFT', mfT('mail.drafts')]];
    const user = (d.labels || []).filter(function (l) { return l.type === 'user'; });
    box.innerHTML = sys.map(function (p) {
      return '<a href="#" class="mail-label" data-label="' + p[0] + '">' + escapeHtml(p[1]) + '</a>';
    }).join('') + user.map(function (l) {
      return '<a href="#" class="mail-label" data-label="' + escapeHtml(l.id) + '">' + escapeHtml(l.name) + '</a>';
    }).join('');
  } catch (e) { /* best-effort */ }
}

async function mfMailLoadThreads(reset) {
  if (reset) { _mailNextPage = null; }
  const box = document.getElementById('mail-thread-list');
  if (!box) return;
  const q = (document.getElementById('mail-search') || {}).value || '';
  const params = new URLSearchParams({label: _mailLabel});
  if (q) params.set('q', q);
  if (_mailNextPage) params.set('page_token', _mailNextPage);
  try {
    const d = await (await fetch('/mail/api/threads?' + params.toString())).json();
    const rows = (d.threads || []).map(function (t) {
      return '<div class="mail-thread-row" data-thread="' + escapeHtml(t.id) + '">' +
        escapeHtml(t.snippet || '(…)') + '</div>';
    }).join('');
    box.innerHTML = (reset ? '' : box.innerHTML) + (rows || '<div class="muted">' + mfT('mail.empty') + '</div>');
    _mailNextPage = d.next_page_token || null;
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('mail.empty') + '</div>'; }
}

function _mailRenderBody(html) {
  // corpo email in iframe sandboxed (no script). Immagini remote bloccate: si
  // neutralizza src http(s) sostituendolo con data-src finché l'utente non clicca "Mostra immagini".
  const blocked = (html || '').replace(/(<img\b[^>]*?)\ssrc=/gi, '$1 data-blocked-src=');
  const doc = '<!doctype html><html><head><meta charset="utf-8">' +
    '<base target="_blank"></head><body>' + blocked + '</body></html>';
  return '<iframe class="mail-body-frame" sandbox="" srcdoc="' +
    doc.replace(/"/g, '&quot;') + '"></iframe>';
}

async function mfMailOpenThread(threadId) {
  const box = document.getElementById('mail-reading');
  if (!box) return;
  try {
    const t = await (await fetch('/mail/api/thread/' + encodeURIComponent(threadId))).json();
    box.innerHTML = (t.messages || []).map(function (m) {
      const atts = (m.attachments || []).map(function (a) {
        return '<a class="mail-att" href="/mail/api/attachment/' + encodeURIComponent(m.id) + '/' +
          encodeURIComponent(a.id) + '?filename=' + encodeURIComponent(a.filename) +
          '&mime=' + encodeURIComponent(a.mime_type) + '">📎 ' + escapeHtml(a.filename) + '</a>';
      }).join(' ');
      const bodyHtml = m.body_html || ('<pre>' + escapeHtml(m.body_text || '') + '</pre>');
      return '<div class="mail-msg"><div class="mail-msg-head"><b>' + escapeHtml(m.from) +
        '</b><span class="muted"> · ' + escapeHtml(m.date) + '</span><div>' + escapeHtml(m.subject) +
        '</div></div>' + _mailRenderBody(bodyHtml) + '<div class="mail-atts">' + atts + '</div>' +
        '<div class="mail-msg-actions">' +
        '<button class="btn btn-sm" data-mail-reply="' + escapeHtml(m.id) + '" data-thread="' + escapeHtml(threadId) + '">' + mfT('mail.reply') + '</button> ' +
        '<button class="btn btn-sm" data-mail-forward="' + escapeHtml(m.id) + '">' + mfT('mail.forward') + '</button>' +
        '</div></div>';
    }).join('') || '<div class="muted">' + mfT('mail.empty') + '</div>';
    // memorizza l'ultimo messaggio per reply/forward
    box._lastThread = t;
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('mail.sendError') + '</div>'; }
}

function mfMailCompose(prefill) {
  prefill = prefill || {};
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  ov.querySelector('[name=to]').value = prefill.to || '';
  ov.querySelector('[name=cc]').value = prefill.cc || '';
  ov.querySelector('[name=subject]').value = prefill.subject || '';
  ov.querySelector('[name=body]').value = prefill.body || '';
  ov.querySelector('[name=thread_id]').value = prefill.thread_id || '';
  ov.querySelector('[name=in_reply_to]').value = prefill.in_reply_to || '';
  ov.classList.remove('hidden');
}

async function mfMailSend() {
  const ov = document.getElementById('mail-compose');
  if (!ov) return;
  if (!confirm(mfT('mail.sendConfirm'))) return;
  const fd = new FormData();
  ['to', 'cc', 'bcc', 'subject', 'body', 'thread_id', 'in_reply_to', 'references'].forEach(function (n) {
    const el = ov.querySelector('[name=' + n + ']');
    if (el && el.value) fd.append(n, el.value);
  });
  const fileInp = ov.querySelector('[name=attachments]');
  if (fileInp && fileInp.files) { for (const f of fileInp.files) fd.append('attachments', f); }
  try {
    const r = await (await fetch('/mail/api/send', {method: 'POST', body: fd})).json();
    if (r.ok) { if (window.toast) toast(mfT('mail.sentOk'), 'success'); ov.classList.add('hidden'); mfMailLoadThreads(true); }
    else { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('mail.sendError'), 'error'); }
}

document.addEventListener('click', function (ev) {
  const t = ev.target;
  const lab = t.closest && t.closest('[data-label]');
  if (lab) { ev.preventDefault(); _mailLabel = lab.getAttribute('data-label'); mfMailLoadThreads(true); return; }
  const row = t.closest && t.closest('[data-thread]');
  if (row && row.classList.contains('mail-thread-row')) { mfMailOpenThread(row.getAttribute('data-thread')); return; }
  const rep = t.closest && t.closest('[data-mail-reply]');
  if (rep) {
    const box = document.getElementById('mail-reading');
    const thr = box && box._lastThread;
    const m = thr && (thr.messages || []).find(function (x) { return x.id === rep.getAttribute('data-mail-reply'); });
    if (m) mfMailCompose({to: m.from, subject: 'Re: ' + (m.subject || ''), thread_id: rep.getAttribute('data-thread'), body: ''});
    return;
  }
  const fw = t.closest && t.closest('[data-mail-forward]');
  if (fw) {
    const box = document.getElementById('mail-reading');
    const thr = box && box._lastThread;
    const m = thr && (thr.messages || []).find(function (x) { return x.id === fw.getAttribute('data-mail-forward'); });
    if (m) mfMailCompose({subject: 'Fwd: ' + (m.subject || ''), body: '\n\n---\n' + (m.body_text || '')});
    return;
  }
  const imgBtn = t.closest && t.closest('[data-mail-show-images]');
  if (imgBtn) {
    const frame = imgBtn.parentElement.querySelector('.mail-body-frame');
    if (frame) frame.setAttribute('srcdoc', frame.getAttribute('srcdoc').replace(/data-blocked-src=/gi, 'src='));
    return;
  }
});
```

- [ ] **Step 5: Create `mail.html`**

```html
{% extends "base.html" %}
{% block content %}
<div class="mail-layout">
  <aside class="mail-nav">
    <button class="btn btn-primary btn-block" onclick="mfMailCompose()" data-i18n="mail.compose">Scrivi</button>
    <div id="mail-labels" class="mail-labels"></div>
  </aside>
  <section class="mail-list">
    <input id="mail-search" class="form-input" data-i18n-attr="placeholder" data-i18n="mail.search"
           placeholder="Cerca nella posta…" onkeydown="if(event.key==='Enter')mfMailLoadThreads(true)">
    <div id="mail-thread-list" class="mail-thread-list"></div>
  </section>
  <section id="mail-reading" class="mail-reading"></section>
</div>

<div id="mail-compose" class="modal-overlay hidden">
  <div class="modal">
    <input name="to" class="form-input" data-i18n-attr="placeholder" data-i18n="mail.to" placeholder="A">
    <input name="cc" class="form-input" placeholder="Cc">
    <input name="bcc" class="form-input" placeholder="Bcc">
    <input name="subject" class="form-input" data-i18n-attr="placeholder" data-i18n="mail.subject" placeholder="Oggetto">
    <textarea name="body" class="form-input" rows="10"></textarea>
    <input type="hidden" name="thread_id"><input type="hidden" name="in_reply_to"><input type="hidden" name="references">
    <input type="file" name="attachments" multiple>
    <div class="modal-actions">
      <button class="btn btn-primary" onclick="mfMailSend()" data-i18n="mail.send">Invia</button>
      <button class="btn btn-secondary" onclick="document.getElementById('mail-compose').classList.add('hidden')">✕</button>
    </div>
  </div>
</div>

<script src="/static/js/mail.js?v={{ app_version }}"></script>
<script>document.addEventListener('DOMContentLoaded', function(){ mfMailInit(); });</script>
{% endblock %}
```

Adatta le classi (`modal-overlay`,`modal`,`form-input`,`btn`) a quelle reali del progetto se differiscono; segui il pattern di un template modale esistente (es. `event_modal` o `documents.js` embed).

- [ ] **Step 6: Sidebar + settings opt-in**

In `app/templates/base.html`, dopo la voce Calendar (riga ~85-87):
```html
        <a href="/mail" data-nav-id="mail" class="nav-item {% if active_page == 'mail' %}active{% endif %}">
          <span class="nav-icon"><i data-lucide="mail"></i></span> <span data-i18n="nav.mail">Email</span>
        </a>
```

Nella card Google di `/settings` (individua il template della tab Account — cerca `oauth/google/start` o la card "Google"), aggiungi accanto al connect un bottone opt-in email (mostralo sempre; se già connesso email, il flusso ripete il consenso senza danno):
```html
<a class="btn btn-secondary btn-sm" href="/auth/oauth/google/start?scopes=email" data-i18n="mail.connect">Collega Gmail</a>
```

- [ ] **Step 7: Run test + JS syntax**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_page.py -v`
Expected: PASS (4 passed).
Run: `node --check app/static/js/mail.js` → nessun errore.
Run: `node --check app/static/js/i18n.js` → nessun errore.

- [ ] **Step 8: Commit**

```bash
git add app/templates/pages/mail.html app/static/js/mail.js app/static/js/i18n.js app/templates/base.html app/templates/pages/settings.html tests/test_mail_page.py
git commit -F <msgfile>
# "feat(mail): frontend /mail 3-pannelli + compose + sidebar + opt-in settings"
```

(Adatta il path del template settings a quello reale — potrebbe non essere `settings.html`.)

---

### Task 7: Chiusura fase — bump + suite + smoke + docs

**Files:**
- Modify: `app/main.py` (`.243` → `.244`), `.env.example`, `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: `.env.example` — nota Gmail API**

Sotto il blocco OAuth (dopo `GOOGLE_PICKER_API_KEY`):
```
# Client email (/mail): richiede l'API Gmail abilitata nel progetto Google Cloud
# e gli scope gmail.readonly + gmail.compose (richiesti in opt-in da /settings).
# Nessuna nuova variabile: riusa GOOGLE_OAUTH_CLIENT_ID/SECRET di Fase A.
```

- [ ] **Step 2: Bump**

`app/main.py`: `version="3.5.0-alpha.172.243"` → `"3.5.0-alpha.172.244"`.

- [ ] **Step 3: CHANGELOG** (nuova voce in cima)

```markdown
## v3.5.0-alpha.172.244 — Client email Sotto-fase 1: /mail webmail standalone (7 lug 2026)

- **Pagina `/mail`**: client webmail su Gmail — lista/ricerca thread, vista conversazione, nav label, scarica allegati; compose Nuovo/Rispondi/Rispondi-a-tutti/Inoltra + allegati + bozze; invio via Gmail API.
- **Opt-in Gmail incrementale**: scope `gmail.readonly` + `gmail.compose` richiesti solo su azione esplicita (`/auth/oauth/google/start?scopes=email`, `include_granted_scopes=true`), NON nel bundle di default. Spento di default.
- **Service** `app/services/gmail.py` (urllib, `_gmail_request` mockabile, MIME via stdlib) + **router** `app/routers/mail.py` (proxy stateless, nessuna tabella/migrazione, per-utente).
- **Sicurezza**: corpo email in iframe `sandbox=""` (no script), immagini remote bloccate di default con toggle, conferma invio, allegati come download, nessun token al client.
- Best-effort: chiamate Gmail fallite → risposta vuota, mai 500. i18n 5 lingue (`mail.*`). Prima delle 3 sotto-fasi Client email (2 = integrazione CRM, 3 = auto-flow).
```

- [ ] **Step 4: STATO** — versione → `.244`; sezione `### α.172.244 ✅ (Client email Sotto-fase 1 — /mail — 7 lug)` coi punti sopra; **Prossimo step** → smoke Matteo + Sotto-fase 2 (integrazione CRM: tab Email, pin `EmailLink`, Estrai-AI, log Activity). Nota prereq: abilitare Gmail API nel progetto Google Cloud + opt-in email da /settings.

- [ ] **Step 5: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (1103 + ~30 nuovi).

- [ ] **Step 6: Smoke browser (uvicorn no-reload)**

Avvia uvicorn (vedi Global Constraints). Login `admin@mediaflow.it`/`admin123`. Vai a `/mail`: senza opt-in Gmail → CTA "Collega Gmail" (nessun errore console). Verifica che la voce sidebar "Email" compaia e la pagina renda i 3 pannelli. (Il flusso live lettura/invio richiede OAuth Google reale + opt-in — non verificabile senza credenziali; verifica il degrado grazioso.) 0 errori console. Chiudi il server.

- [ ] **Step 7: Commit**

```bash
git add app/main.py .env.example CHANGELOG.md docs/STATO.md
git commit -F <msgfile>
# "chore(mail): Client email Sotto-fase 1 v3.5.0-alpha.172.244"
```

---

## Self-Review

**1. Spec coverage:**
- Scope `gmail.readonly`+`gmail.compose` opt-in incrementale → Task 1 ✓
- Service stateless (list/get/send/draft/labels/attachment, best-effort, MIME) → Task 2+3 ✓
- Router proxy stateless + status degrado grazioso → Task 4+5 ✓
- Pagina 3-pannelli + compose (Nuovo/Rispondi/Rispondi-tutti/Inoltra) + allegati + bozze → Task 6 ✓
- Sicurezza: iframe sandbox + blocco immagini remote + conferma invio + allegati download + no token al client → Task 4 (attachment header) + Task 6 (`_mailRenderBody`, confirm) ✓
- Nessuna migrazione (stateless) → confermato (nessun modello/ALTER) ✓
- i18n 5 lingue → Task 6 ✓
- Sidebar + settings opt-in → Task 6 ✓
- Bump/CHANGELOG/STATO/.env → Task 7 ✓

**2. Placeholder scan:** nessun TBD/TODO. Due punti richiedono all'implementatore di adattare al codebase reale (import `templates`, path/markup card `/settings`, classi CSS modale): sono note esplicite con il pattern da seguire, non placeholder di codice. Il codice funzionale è completo.

**3. Type consistency:**
- `_gmail_request(method, path, token, params=None, body=None)` — firma identica in Task 2 (def), Task 3 (uso), Task 4/5 (mock nei test).
- `list_threads(...)->{"threads","next_page_token"}`, `get_thread(...)->{"id","messages"}|None`, `_normalize_message` chiavi (`from,to,cc,subject,date,snippet,body_html,body_text,attachments[{id,filename,mime_type,size}]`) coerenti tra service (Task 2), router (Task 4), frontend (`mfMailOpenThread` Task 6).
- `send_message(...to,subject,body_html,cc,bcc,in_reply_to,references,thread_id,attachments)->dict|None` coerente Task 3 (def) / Task 5 (uso, kwargs) / test.
- `build_mime(...)->str` (base64url) coerente Task 3 def+test.
- Funzioni JS globali `mfMailInit/LoadThreads/OpenThread/Compose/Send` coerenti Task 6 (impl+test+html).
- `GET /auth/oauth/google/start?scopes=email` coerente Task 1 (router) + Task 6 (link frontend/settings).

## Note

- `UserOAuthToken.scopes` esiste già (salvato dal callback OAuth) → `/mail/api/status` lo interroga senza migrazioni.
- Fixture test router: override `current_user` via `monkeypatch.setattr(app.routers.mail, "current_user", ...)` (i simboli sono legati nel modulo `mail`), pattern di `test_documents_api.py`.
- Il flusso live (lettura/invio reali) richiede: Gmail API abilitata nel progetto Google Cloud + opt-in email da `/settings`. Senza, tutto degrada a CTA "Collega Gmail" senza errori.
- Sotto-fase 2 (CRM: tab Email + pin `EmailLink` + Estrai-AI Fase 2 + log Activity) riuserà `gmail.get_thread`/`list_threads` di questa fase.
