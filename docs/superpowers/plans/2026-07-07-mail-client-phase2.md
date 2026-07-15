# Client email — Sotto-fase 2: integrazione CRM (trattativa) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agganciare thread email Gmail alle trattative (acquisitions): pin (ricerca-in-tab / incolla-link / da `/mail`), lista + anteprima nel tab Email, log Activity automatico, "Estrai con AI" via copilot.

**Architecture:** Modello `EmailLink` (pattern `DocumentLink` di Fase D, ancorato solo a `acquisition_id`). Router `email_links.py` (pin/list/delete, auto-`Activity(type=email)`), riusa `gmail.py` (F1) per metadata/anteprima e il copilot (Fase 2) per l'estrazione. Frontend: tab Email in `acquisitions.html` + `email_links.js`; bottone "Assegna a trattativa" in `mail.js` che riusa `GET /acquisitions/api/list`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, urllib (via gmail.py F1), vanilla JS, i18n client-side.

## Global Constraints

- **Ramo:** `feat/mail-client-phase2`. Nessun push finché Matteo non fa smoke.
- **Nessuna nuova dipendenza Python.** Riusa `app/services/gmail.py` (F1): `get_thread`, e il nuovo `parse_gmail_thread_id` (Task 2).
- **Tenant:** `current_tenant_id()` da `app.context`; query tenant-scoped via `app.services.tenant_guard.scoped`/`fetch_or_404` (NO kwarg tenant_id).
- **Soft-delete:** `is_active=False`, mai DELETE fisico. Letture filtrano `is_active == True`.
- **RBAC runtime** per `linked_type` acquisition: view `view_acquisitions`, manage `manage_acquisitions`, via `has_permission(user, perm)` (`app.services.rbac`), pattern di `app/routers/documents.py`. `current_user(request)` da `app.services.rbac`.
- **Form-based** per scrittura (`Form(...)`). **i18n 5 lingue** (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`. **cache-buster** `?v={app_version}` su JS nuovo. Helper globali (`escapeHtml`,`api`,`toast`,`mfT`) da `global.js`, non ridefiniti. No `JSON.stringify` in onclick → `data-*`. `mfT(key)` 1-arg.
- **Sicurezza:** anteprima corpo email in iframe `sandbox=""` (no script) via `srcdoc`; link/URL http(s) only + `rel="noopener noreferrer"`; nessun token Gmail verso il client (chiamate via router F1). `parse_gmail_thread_id` su URL non-Gmail → 400.
- **Modello Activity** (esistente): `Activity(tenant_id, acquisition_id, type=ActivityType.email, direction=ActivityDirection.inbound, subject, body, occurred_at, created_by, ai_extracted=False, is_active=True)`. Import `ActivityType, ActivityDirection` da `app.models.models`.
- **Copilot inject** (esistente, `copilot.html`): `document.getElementById('cp-input').value = ...; copilotSend();` (usa chiavi `copilot.email.instruction`).
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (heredoc bloccato da hook; `printf` in bash).
- **Versione:** `3.5.0-alpha.172.244` → `.245` (Task 6).
- **Smoke server:** uvicorn SENZA reload, `127.0.0.1`, NON `APP_ENV=production`.

---

### Task 1: Modello `EmailLink` + migrazione

**Files:**
- Modify: `app/models/models.py` (nuova classe dopo `DocumentLink`)
- Create: `scripts/migrate_email_links.py`
- Modify: `strumenti.bat`, `strumenti.sh` (voce migrazione, pattern `migrate_documents.py`)
- Test: `tests/test_email_link_model.py`

**Interfaces:**
- Produces: `EmailLink` (tabella `email_links`) con colonne `id, tenant_id, provider, thread_id, message_id, from_addr, subject, snippet, email_date, acquisition_id, added_by, created_at, is_active`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_link_model.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, EmailLink


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_email_link_columns():
    cols = {c.name for c in EmailLink.__table__.columns}
    assert {"id", "tenant_id", "provider", "thread_id", "message_id", "from_addr",
            "subject", "snippet", "email_date", "acquisition_id", "added_by",
            "created_at", "is_active"} <= cols


def test_email_link_defaults():
    s = _session()
    e = EmailLink(tenant_id=1, thread_id="T1", subject="Oggetto", acquisition_id=5)
    s.add(e); s.commit(); s.refresh(e)
    assert e.provider == "google"
    assert e.is_active is True
    assert e.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_link_model.py -v`
Expected: FAIL (`ImportError: cannot import name 'EmailLink'`).

- [ ] **Step 3: Add the model**

In `app/models/models.py`, subito dopo la classe `DocumentLink`:

```python
class EmailLink(Base):
    """Riferimento a un thread Gmail agganciato a una trattativa (Client email F2).
    Nessuno storage del corpo: solo metadata + thread_id. Tenant-scoped, soft-delete."""
    __tablename__ = "email_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    provider: Mapped[str] = mapped_column(String(20), default="google", nullable=False)
    thread_id: Mapped[str] = mapped_column(String(255), index=True)
    message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    from_addr: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    snippet: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_date: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    acquisition_id: Mapped[int] = mapped_column(ForeignKey("acquisitions.id"), index=True)
    added_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_link_model.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Create migration script**

```python
# scripts/migrate_email_links.py
"""Migrazione Client email F2 — tabella email_links (idempotente).
Creata anche da Base.metadata.create_all() al boot; questo script per DB esistenti.
Uso: .venv/Scripts/python.exe scripts/migrate_email_links.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect
from app.database import engine
from app.models.models import EmailLink  # noqa: F401


def main():
    insp = inspect(engine)
    if "email_links" in insp.get_table_names():
        print("[migrate_email_links] tabella email_links già presente — nessuna azione.")
        return
    EmailLink.__table__.create(bind=engine)
    print("[migrate_email_links] tabella email_links creata.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run migration smoke**

Run: `.venv/Scripts/python.exe scripts/migrate_email_links.py`
Expected: stampa "creata" o "già presente" senza traceback.

- [ ] **Step 7: strumenti voce**

In `strumenti.bat`: aggiungi opzione `[S]` (menu display dopo `[R]`, dispatch, label) che esegue `python scripts\migrate_email_links.py`, seguendo il blocco `:migrate_documents`. In `strumenti.sh`: aggiungi caso `s|S)` dopo `r|R)` + voce menu, con `python scripts/migrate_email_links.py`. Etichetta: "Migra Client email F2 - email_links".

- [ ] **Step 8: Commit**

```bash
git add app/models/models.py scripts/migrate_email_links.py strumenti.bat strumenti.sh tests/test_email_link_model.py
git commit -F <msgfile>
# "feat(mail): modello EmailLink + migrazione (F2)"
```

---

### Task 2: `parse_gmail_thread_id` in `gmail.py`

**Files:**
- Modify: `app/services/gmail.py` (aggiunge `parse_gmail_thread_id`, import `re`)
- Test: `tests/test_gmail_parse_thread.py`

**Interfaces:**
- Produces: `parse_gmail_thread_id(url: str) -> Optional[str]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gmail_parse_thread.py
from app.services import gmail


def test_parse_inbox_fragment():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/0/#inbox/FMfcgzABC123") == "FMfcgzABC123"


def test_parse_label_fragment():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/0/#label/Clienti/FMfcgzXYZ") == "FMfcgzXYZ"


def test_parse_search_fragment():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/2/#search/foo/FMfcgzQ9") == "FMfcgzQ9"


def test_parse_th_param():
    assert gmail.parse_gmail_thread_id(
        "https://mail.google.com/mail/u/0/?th=abc123def") == "abc123def"


def test_parse_non_gmail_none():
    assert gmail.parse_gmail_thread_id("https://example.com/x") is None


def test_parse_gmail_no_id_none():
    assert gmail.parse_gmail_thread_id("https://mail.google.com/mail/u/0/#inbox") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_parse_thread.py -v`
Expected: FAIL (`AttributeError: parse_gmail_thread_id`).

- [ ] **Step 3: Add the function**

In `app/services/gmail.py`, aggiungi `import re` in cima (se assente) e la funzione (vicino a `_b64url_decode`):

```python
import re  # in cima, con gli altri import


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_parse_thread.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/gmail.py tests/test_gmail_parse_thread.py
git commit -F <msgfile>
# "feat(mail): parse_gmail_thread_id (URL Gmail → thread id)"
```

---

### Task 3: Router `email_links.py` — pin/list/delete + auto-Activity + registrazione

**Files:**
- Create: `app/routers/email_links.py`
- Modify: `app/main.py` (import + `include_router` vicino a `mail_router`)
- Test: `tests/test_email_links_api.py`

**Interfaces:**
- Consumes: `EmailLink` (Task 1); `parse_gmail_thread_id`, `get_thread` (gmail); `has_permission`, `current_user` (rbac); `scoped`, `fetch_or_404` (tenant_guard); `current_tenant_id` (context); `Acquisition`, `Activity`, `ActivityType`, `ActivityDirection` (models).
- Produces:
  - `POST /acquisitions/api/{aid}/emails/link` (Form: opz `url`, `thread_id`, `message_id`, `from_addr`, `subject`, `snippet`, `email_date`) → `EmailLink` serializzato.
  - `GET /acquisitions/api/{aid}/emails` → `{"emails": [...]}`.
  - `DELETE /email-links/{link_id}` → `{"ok": True}`.
  - `_serialize_email(e) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_email_links_api.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (Base, Tenant, User, UserRole, Client, Acquisition, Activity)
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Acquisition(id=1, tenant_id=1, prospect_name="Trattativa", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_pin_by_thread_id_creates_link_and_activity(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid, "messages": [{"id": "M1", "from": "m@x.com", "subject": "Oggetto",
                                 "snippet": "ciao", "date": "Mon, 7 Jul 2026"}]})
    r = c.post("/acquisitions/api/1/emails/link", data={"thread_id": "T1"})
    assert r.status_code == 200
    b = r.json()
    assert b["thread_id"] == "T1"
    assert b["subject"] == "Oggetto"
    # auto-Activity creata
    acts = s.query(Activity).filter(Activity.acquisition_id == 1).all()
    assert len(acts) == 1
    assert acts[0].type.value == "email"


def test_pin_by_url(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "parse_gmail_thread_id", lambda u: "TZ")
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: None)  # metadata non accessibili
    r = c.post("/acquisitions/api/1/emails/link",
               data={"url": "https://mail.google.com/mail/u/0/#inbox/TZ"})
    assert r.status_code == 200
    assert r.json()["thread_id"] == "TZ"
    assert r.json()["subject"]  # fallback non vuoto


def test_pin_non_gmail_url_400(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "parse_gmail_thread_id", lambda u: None)
    r = c.post("/acquisitions/api/1/emails/link", data={"url": "https://example.com/x"})
    assert r.status_code == 400


def test_list_filtered(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid, "messages": [{"from": "a@b.com", "subject": "S", "snippet": "x", "date": "d"}]})
    c.post("/acquisitions/api/1/emails/link", data={"thread_id": "T1"})
    r = c.get("/acquisitions/api/1/emails")
    assert r.status_code == 200
    assert len(r.json()["emails"]) == 1


def test_delete_soft(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid, "messages": [{"from": "a@b.com", "subject": "S", "snippet": "x", "date": "d"}]})
    lid = c.post("/acquisitions/api/1/emails/link", data={"thread_id": "T2"}).json()["id"]
    assert c.delete(f"/email-links/{lid}").json()["ok"] is True
    r = c.get("/acquisitions/api/1/emails")
    assert all(e["id"] != lid for e in r.json()["emails"])


def test_acquisition_404(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: None)
    r = c.post("/acquisitions/api/999/emails/link", data={"thread_id": "T1"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_links_api.py -v`
Expected: FAIL (404 endpoint assenti).

- [ ] **Step 3: Create `email_links.py`**

```python
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
    acq = fetch_or_404(db, Acquisition, aid)

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
```

- [ ] **Step 4: Register in `main.py`**

Import (con gli altri router):
```python
from app.routers import email_links as email_links_router  # feat/mail-client-phase2
```
Dopo `app.include_router(mail_router.router)`:
```python
app.include_router(email_links_router.router)  # Client email F2 — email agganciate
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_links_api.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Commit**

```bash
git add app/routers/email_links.py app/main.py tests/test_email_links_api.py
git commit -F <msgfile>
# "feat(mail): router email_links pin/list/delete + auto-Activity (F2)"
```

---

### Task 4: Frontend — tab Email in acquisitions + `email_links.js` + i18n

**Files:**
- Create: `app/static/js/email_links.js`
- Modify: `app/templates/pages/acquisitions.html` (tab + content + wiring)
- Modify: `app/static/js/i18n.js` (chiavi `email.*`)
- Test: `tests/test_email_links_page.py`

**Interfaces:**
- Consumes: endpoint Task 3; `/mail/api/threads`, `/mail/api/thread/{id}` (F1); copilot inject (`cp-input`+`copilotSend`).
- Produces: globali `mfEmailInit(aid)`, `mfEmailList(aid)`, `mfEmailSearch(aid)`, `mfEmailPin(aid, payload)`, `mfEmailPinUrl(aid)`, `mfEmailPreview(threadId, containerId)`, `mfEmailExtract(threadId)`, `mfEmailRemove(id, aid)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_links_page.py
import pathlib


def test_acquisitions_has_email_tab():
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert 'data-tab="email"' in html
    assert 'id="det-tab-email"' in html
    assert 'email_links.js' in html


def test_email_links_js_globals():
    src = pathlib.Path("app/static/js/email_links.js").read_text(encoding="utf-8")
    for fn in ("mfEmailInit", "mfEmailList", "mfEmailSearch", "mfEmailPin",
               "mfEmailPinUrl", "mfEmailPreview", "mfEmailExtract", "mfEmailRemove"):
        assert fn in src, fn
    assert "sandbox" in src  # anteprima corpo in iframe sandboxed


def test_i18n_email_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("email.tab", "email.search", "email.pin", "email.pinUrl",
                "email.urlPlaceholder", "email.extract", "email.expand", "email.remove",
                "email.pinned", "email.empty", "email.invalidUrl", "email.error"):
        assert key in src, key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_links_page.py -v`
Expected: FAIL (file/chiavi/tab assenti).

- [ ] **Step 3: Add i18n keys**

In `app/static/js/i18n.js`, vicino alle chiavi `mail.*` (dopo `mail.loadMore`):

```javascript
  'email.tab':          {it: 'Email', en: 'Email', fr: 'E-mail', de: 'E-Mail', es: 'Correo'},
  'email.search':       {it: 'Cerca email del cliente…', en: 'Search client emails…', fr: 'Rechercher les e-mails…', de: 'Kunden-E-Mails suchen…', es: 'Buscar correos…'},
  'email.pin':          {it: 'Aggancia', en: 'Pin', fr: 'Épingler', de: 'Anheften', es: 'Fijar'},
  'email.pinUrl':       {it: 'Aggancia da link', en: 'Pin by link', fr: 'Épingler par lien', de: 'Per Link anheften', es: 'Fijar por enlace'},
  'email.urlPlaceholder': {it: 'Incolla link Gmail…', en: 'Paste Gmail link…', fr: 'Collez le lien Gmail…', de: 'Gmail-Link einfügen…', es: 'Pega el enlace de Gmail…'},
  'email.extract':      {it: 'Estrai con AI', en: 'Extract with AI', fr: 'Extraire avec IA', de: 'Mit KI extrahieren', es: 'Extraer con IA'},
  'email.expand':       {it: 'Anteprima', en: 'Preview', fr: 'Aperçu', de: 'Vorschau', es: 'Vista previa'},
  'email.remove':       {it: 'Rimuovi', en: 'Remove', fr: 'Retirer', de: 'Entfernen', es: 'Quitar'},
  'email.pinned':       {it: 'Email agganciata', en: 'Email pinned', fr: 'E-mail épinglé', de: 'E-Mail angeheftet', es: 'Correo fijado'},
  'email.empty':        {it: 'Nessuna email agganciata', en: 'No pinned emails', fr: 'Aucun e-mail épinglé', de: 'Keine E-Mails angeheftet', es: 'Sin correos fijados'},
  'email.invalidUrl':   {it: 'Link Gmail non valido', en: 'Invalid Gmail link', fr: 'Lien Gmail invalide', de: 'Ungültiger Gmail-Link', es: 'Enlace de Gmail no válido'},
  'email.error':        {it: 'Errore email', en: 'Email error', fr: 'Erreur e-mail', de: 'E-Mail-Fehler', es: 'Error de correo'},
  'email.assign':       {it: 'Assegna a trattativa', en: 'Assign to deal', fr: 'Assigner à une affaire', de: 'Zu Deal zuordnen', es: 'Asignar a negociación'},
  'email.assignOk':     {it: 'Assegnata alla trattativa', en: 'Assigned to deal', fr: 'Assigné', de: 'Zugeordnet', es: 'Asignado'},
```

- [ ] **Step 4: Create `email_links.js`**

```javascript
// app/static/js/email_links.js — Client email F2: email agganciate alla trattativa
let _emClickBound = false;

function _emRenderBody(html) {
  // anteprima corpo in iframe sandboxed (no script), immagini remote bloccate.
  const blocked = (html || '').replace(/(<img\b[^>]*?)\ssrc=/gi, '$1 data-blocked-src=');
  const doc = '<!doctype html><html><head><meta charset="utf-8"><base target="_blank"></head><body>' +
    blocked + '</body></html>';
  return '<iframe class="mail-body-frame" sandbox="" srcdoc="' + doc.replace(/"/g, '&quot;') + '"></iframe>';
}

async function mfEmailList(aid) {
  const box = document.getElementById('em-list');
  if (!box) return;
  try {
    const d = await (await fetch('/acquisitions/api/' + encodeURIComponent(aid) + '/emails')).json();
    const emails = d.emails || [];
    if (!emails.length) { box.innerHTML = '<div class="muted" data-i18n="email.empty">' + mfT('email.empty') + '</div>'; return; }
    box.innerHTML = emails.map(function (e) {
      return '<div class="em-row" style="padding:6px 0;border-bottom:1px solid var(--border);">' +
        '<b>' + escapeHtml(e.subject || '') + '</b> <span class="muted">' + escapeHtml(e.from_addr || '') +
        ' · ' + escapeHtml(e.email_date || '') + '</span><div class="muted">' + escapeHtml(e.snippet || '') + '</div>' +
        '<div style="display:flex;gap:6px;margin-top:4px;">' +
        '<button class="btn btn-sm" data-em-preview="' + escapeHtml(e.thread_id) + '">' + mfT('email.expand') + '</button>' +
        '<button class="btn btn-sm" data-em-extract="' + escapeHtml(e.thread_id) + '">' + mfT('email.extract') + '</button>' +
        '<button class="btn btn-sm" data-em-remove="' + e.id + '" data-em-aid="' + escapeHtml(String(aid)) + '">🗑</button>' +
        '</div><div class="em-preview" id="em-prev-' + escapeHtml(e.thread_id) + '"></div></div>';
    }).join('');
  } catch (err) { box.innerHTML = '<div class="muted">' + mfT('email.error') + '</div>'; }
}

async function mfEmailSearch(aid) {
  const inp = document.getElementById('em-search');
  const box = document.getElementById('em-results');
  if (!inp || !box) return;
  const q = inp.value.trim();
  try {
    const d = await (await fetch('/mail/api/threads?q=' + encodeURIComponent(q))).json();
    const rows = (d.threads || []).map(function (t) {
      return '<div class="em-result" style="display:flex;gap:6px;align-items:center;padding:3px 0;">' +
        '<span style="flex:1;">' + escapeHtml(t.snippet || '(…)') + '</span>' +
        '<button class="btn btn-sm" data-em-pin="' + escapeHtml(t.id) + '" data-em-aid="' + escapeHtml(String(aid)) + '">' + mfT('email.pin') + '</button></div>';
    }).join('');
    box.innerHTML = rows || '<div class="muted">' + mfT('email.empty') + '</div>';
  } catch (err) { box.innerHTML = '<div class="muted">' + mfT('email.error') + '</div>'; }
}

async function mfEmailPin(aid, payload) {
  const fd = new FormData();
  fd.append('acquisition_id_ignore', '');  // no-op per chiarezza; aid è nell'URL
  Object.keys(payload || {}).forEach(function (k) { if (payload[k]) fd.append(k, payload[k]); });
  try {
    const r = await fetch('/acquisitions/api/' + encodeURIComponent(aid) + '/emails/link', {method: 'POST', body: fd});
    if (r.ok) { if (window.toast) toast(mfT('email.pinned'), 'success'); mfEmailList(aid); }
    else if (r.status === 400) { if (window.toast) toast(mfT('email.invalidUrl'), 'error'); }
    else { if (window.toast) toast(mfT('email.error'), 'error'); }
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

async function mfEmailPinUrl(aid) {
  const inp = document.getElementById('em-url');
  if (!inp || !inp.value.trim()) return;
  await mfEmailPin(aid, {url: inp.value.trim()});
  inp.value = '';
}

async function mfEmailPreview(threadId) {
  const box = document.getElementById('em-prev-' + threadId);
  if (!box) return;
  if (box.innerHTML) { box.innerHTML = ''; return; }  // toggle
  try {
    const t = await (await fetch('/mail/api/thread/' + encodeURIComponent(threadId))).json();
    const m = (t.messages || [])[0] || {};
    const html = m.body_html || ('<pre>' + escapeHtml(m.body_text || '') + '</pre>');
    box.innerHTML = _emRenderBody(html);
  } catch (err) { box.innerHTML = '<div class="muted">' + mfT('email.error') + '</div>'; }
}

async function mfEmailExtract(threadId) {
  // riusa il copilot (Fase 2): fetch corpo → inietta come il bottone 📥.
  try {
    const t = await (await fetch('/mail/api/thread/' + encodeURIComponent(threadId))).json();
    const body = (t.messages || []).map(function (m) { return m.body_text || ''; }).join('\n\n');
    const ta = document.getElementById('cp-input');
    if (ta && window.copilotSend) {
      ta.value = mfT('copilot.email.instruction') + '\n\n' + body;
      copilotSend();
    }
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

async function mfEmailRemove(id, aid) {
  try {
    const r = await fetch('/email-links/' + id, {method: 'DELETE'});
    if (r.ok) mfEmailList(aid);
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}

function mfEmailInit(aid) {
  if (!_emClickBound) {
    _emClickBound = true;
    document.addEventListener('click', function (ev) {
      const t = ev.target;
      const pin = t.closest && t.closest('[data-em-pin]');
      if (pin) { mfEmailPin(pin.getAttribute('data-em-aid'), {thread_id: pin.getAttribute('data-em-pin')}); return; }
      const prev = t.closest && t.closest('[data-em-preview]');
      if (prev) { mfEmailPreview(prev.getAttribute('data-em-preview')); return; }
      const ext = t.closest && t.closest('[data-em-extract]');
      if (ext) { mfEmailExtract(ext.getAttribute('data-em-extract')); return; }
      const rem = t.closest && t.closest('[data-em-remove]');
      if (rem) { mfEmailRemove(rem.getAttribute('data-em-remove'), rem.getAttribute('data-em-aid')); return; }
    });
  }
  mfEmailList(aid);
}
```

- [ ] **Step 5: Embed tab in `acquisitions.html`**

Aggiungi il bottone tab dopo il tab documents (riga ~258):
```html
      <button class="acq-det-tab" data-tab="email" onclick="acqDetTab(this,'email')" data-i18n="email.tab">Email</button>
```
Aggiungi il contenuto dopo `det-tab-documents` (riga ~345, dopo la chiusura del div documents):
```html
    {# 📧 Email agganciate (Client email F2) #}
    <div class="acq-det-content" id="det-tab-email">
      <div style="display:flex;gap:6px;margin-bottom:6px;">
        <input id="em-search" class="form-input" style="flex:1;" data-i18n-attr="placeholder" data-i18n="email.search" placeholder="Cerca email del cliente…">
        <button class="btn btn-secondary btn-sm" id="em-search-btn" data-i18n="email.search">Cerca</button>
      </div>
      <div id="em-results" class="mb-2"></div>
      <div style="display:flex;gap:6px;margin-bottom:8px;">
        <input id="em-url" class="form-input" style="flex:1;" data-i18n-attr="placeholder" data-i18n="email.urlPlaceholder" placeholder="Incolla link Gmail…">
        <button class="btn btn-secondary btn-sm" id="em-url-btn" data-i18n="email.pinUrl">Aggancia da link</button>
      </div>
      <div id="em-list"></div>
    </div>
```
Includi lo script (vicino a `documents.js`, riga ~480):
```html
<script src="/static/js/email_links.js?v={{ app_version }}"></script>
```
Nel JS del pannello, dove si aprono i tab documents (funzione `acqDetTab`, riga ~834 dove c'è `if (tab === 'documents' ...)`), aggiungi:
```javascript
  if (tab === 'email' && _acqCurrentId) mfEmailInit(_acqCurrentId);
```
E in `acqOpenDetail` (dove viene wired il tab documents, righe ~814-816), aggiungi il wiring dei bottoni email:
```javascript
    document.getElementById('em-search-btn').onclick = function () { mfEmailSearch(aid); };
    document.getElementById('em-url-btn').onclick = function () { mfEmailPinUrl(aid); };
    document.getElementById('em-search').value = '';
```

- [ ] **Step 6: Run test + JS syntax**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_links_page.py -v`
Expected: PASS (3 passed).
Run: `node --check app/static/js/email_links.js` → nessun errore.
Run: `node --check app/static/js/i18n.js` → nessun errore.

- [ ] **Step 7: Commit**

```bash
git add app/static/js/email_links.js app/static/js/i18n.js app/templates/pages/acquisitions.html tests/test_email_links_page.py
git commit -F <msgfile>
# "feat(mail): tab Email trattativa + email_links.js (pin/anteprima/estrai-AI) (F2)"
```

---

### Task 5: "Assegna a trattativa" da `/mail`

**Files:**
- Modify: `app/static/js/mail.js` (bottone assign nel pannello lettura + picker)
- Test: `tests/test_mail_assign.py`

**Interfaces:**
- Consumes: `GET /acquisitions/api/list` (esistente), `POST /acquisitions/api/{aid}/emails/link` (Task 3).
- Produces: `mfMailAssign(threadId)` globale + bottone `data-mail-assign` nel rendering thread.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mail_assign.py
import pathlib


def test_mail_js_has_assign():
    src = pathlib.Path("app/static/js/mail.js").read_text(encoding="utf-8")
    assert "mfMailAssign" in src
    assert "data-mail-assign" in src
    assert "/acquisitions/api/list" in src


def test_i18n_assign_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    assert "email.assign" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_assign.py -v`
Expected: FAIL (`mfMailAssign` assente).

- [ ] **Step 3: Add assign to `mail.js`**

Nel rendering di `mfMailOpenThread`, dentro `.mail-msg-actions` (dopo il bottone forward), aggiungi il bottone assign una volta per thread (usa il primo messaggio; il bottone porta il `threadId`):

Modifica la stringa delle azioni per includere:
```javascript
        '<button class="btn btn-sm" data-mail-assign="' + escapeHtml(threadId) + '">' + mfT('email.assign') + '</button>' +
```
(inseriscilo accanto ai bottoni reply/forward nello stesso blocco `mail-msg-actions`).

Aggiungi la funzione e l'handler (in fondo a `mail.js`, prima o dopo il listener esistente):
```javascript
async function mfMailAssign(threadId) {
  try {
    const d = await (await fetch('/acquisitions/api/list')).json();
    const items = (d.acquisitions || d.items || d || []);
    const list = Array.isArray(items) ? items : (items.acquisitions || []);
    if (!list.length) { if (window.toast) toast(mfT('email.empty'), 'error'); return; }
    const label = list.map(function (a, i) {
      return (i + 1) + '. ' + (a.prospect_name || a.title || ('#' + a.id));
    }).join('\n');
    const pick = prompt(mfT('email.assign') + '\n' + label);
    if (!pick) return;
    const idx = parseInt(pick, 10) - 1;
    const acq = list[idx];
    if (!acq) return;
    const fd = new FormData();
    fd.append('thread_id', threadId);
    const r = await fetch('/acquisitions/api/' + acq.id + '/emails/link', {method: 'POST', body: fd});
    if (r.ok) { if (window.toast) toast(mfT('email.assignOk'), 'success'); }
    else { if (window.toast) toast(mfT('email.error'), 'error'); }
  } catch (err) { if (window.toast) toast(mfT('email.error'), 'error'); }
}
```
Nel listener click globale di `mail.js`, aggiungi il ramo:
```javascript
  const asg = t.closest && t.closest('[data-mail-assign]');
  if (asg) { mfMailAssign(asg.getAttribute('data-mail-assign')); return; }
```

- [ ] **Step 4: Run test + JS syntax**

Run: `.venv/Scripts/python.exe -m pytest tests/test_mail_assign.py -v`
Expected: PASS (2 passed).
Run: `node --check app/static/js/mail.js` → nessun errore.

- [ ] **Step 5: Commit**

```bash
git add app/static/js/mail.js tests/test_mail_assign.py
git commit -F <msgfile>
# "feat(mail): assegna thread a trattativa da /mail (F2)"
```

---

### Task 6: Chiusura fase — bump + suite + smoke + docs

**Files:**
- Modify: `app/main.py` (`.244` → `.245`), `CHANGELOG.md`, `docs/STATO.md`

- [ ] **Step 1: Bump**

`app/main.py`: `version="3.5.0-alpha.172.244"` → `"3.5.0-alpha.172.245"`.

- [ ] **Step 2: CHANGELOG** (nuova voce in cima)

```markdown
## v3.5.0-alpha.172.245 — Client email Sotto-fase 2: integrazione CRM (trattativa) (7 lug 2026)

- **`EmailLink`** (`email_links`, tenant-scoped, soft-delete): aggancia thread Gmail alle **trattative** salvando solo metadata + `thread_id`.
- **Tab "Email"** nel detail trattativa `/acquisitions`: ricerca Gmail nel tab + incolla-link → **Pin**; lista pinnati con **anteprima** (iframe sandbox), **Estrai con AI**, 🗑. Il pin logga un'**Activity(type=email)** automatica in timeline.
- **"Assegna a trattativa"** dal client `/mail` (pannello lettura) → picker trattative → pin.
- **Estrai con AI** = iniezione nel copilot (riusa l'estrazione email di Acquisizioni Fase 2 → `propose_activity/contact/update_client/acquisition_stage`), nessun backend AI nuovo.
- Router `app/routers/email_links.py` (pin/list/delete, RBAC acquisitions, tenant-scope) + `gmail.parse_gmail_thread_id`. Migrazione `scripts/migrate_email_links.py` + voce strumenti. i18n 5 lingue (`email.*`). Seconda delle 3 sotto-fasi Client email.
```

- [ ] **Step 3: STATO** — versione → `.245`; sezione `### α.172.245 ✅ (Client email Sotto-fase 2 — CRM trattativa — 7 lug)` coi punti sopra; **Prossimo step** → smoke Matteo + Sotto-fase 3 (auto-flow: auto-associazione per indirizzo, AI senza pin manuale, notifiche). Ramo `feat/mail-client-phase2` NON pushato.

- [ ] **Step 4: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (1133 + ~17 nuovi).

- [ ] **Step 5: Smoke browser (uvicorn no-reload)**

Avvia uvicorn (Global Constraints). Login `admin@mediaflow.it`/`admin123`. Apri una trattativa in `/acquisitions` → tab **Email**: incolla un link Gmail (`https://mail.google.com/mail/u/0/#inbox/TESTID`) → **Aggancia da link** → compare in lista (subject fallback "Email" se non accessibile) + un'Activity "email" nel tab Attività; **Anteprima** apre l'iframe; 🗑 rimuove. Su `/mail` (se senza opt-in Gmail → CTA, ok). 0 errori console. Chiudi il server.

- [ ] **Step 6: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -F <msgfile>
# "chore(mail): Client email Sotto-fase 2 v3.5.0-alpha.172.245"
```

---

## Self-Review

**1. Spec coverage:**
- `EmailLink` (ancorato acquisition) + migrazione → Task 1 ✓
- `parse_gmail_thread_id` → Task 2 ✓
- Router pin/list/delete + auto-Activity → Task 3 ✓
- Ricerca-in-tab + incolla-link + anteprima sandbox + Estrai-AI (copilot) + tab Email → Task 4 ✓
- "Assegna a trattativa" da /mail (riusa /acquisitions/api/list) → Task 5 ✓
- Estrai-AI via copilot (no backend AI) → Task 4 (`mfEmailExtract`) ✓
- Sicurezza iframe sandbox + http(s) + parse 400 → Task 3 (400) + Task 4 (`_emRenderBody`) ✓
- i18n 5 lingue → Task 4 ✓
- Bump/CHANGELOG/STATO + suite + smoke → Task 6 ✓

**2. Placeholder scan:** nessun TBD/TODO. Il wiring in `acquisitions.html` (Task 4 Step 5) richiede di posizionare gli hook nei punti reali (`acqDetTab`, `acqOpenDetail`) seguendo il pattern del tab documents già presente — istruzioni con righe di riferimento, non placeholder. Il campo `acquisition_id_ignore` in `mfEmailPin` è un no-op innocuo (aid è nell'URL); l'implementatore può ometterlo.

**3. Type consistency:**
- `EmailLink` colonne coerenti Task 1 (def) / Task 3 (`_serialize_email`, create) / Task 4 (consumo JSON: `subject,from_addr,email_date,snippet,thread_id,id`).
- `pin_email` Form params (`url,thread_id,message_id,from_addr,subject,snippet,email_date`) coerenti con `mfEmailPin` payload keys.
- `parse_gmail_thread_id(url)->Optional[str]` Task 2 (def) / Task 3 (uso) / test.
- Globali JS `mfEmailInit/List/Search/Pin/PinUrl/Preview/Extract/Remove` + `mfMailAssign` coerenti Task 4/5 (impl+test+embed).
- `has_permission(user, perm)`, `current_user(request)`, `fetch_or_404(db, model, id)`, `scoped(query, model)`, `current_tenant_id()` — firme verificate (Fase D).
- Activity: `type=ActivityType.email`, `direction=ActivityDirection.inbound` — enum verificati in `models.py:181-186`.

## Note

- La tabella `email_links` è creata da `create_all` al boot; `migrate_email_links.py` per DB esistenti (nessun ALTER, tabella nuova).
- Fixture test router: JWT cookie reale + monkeypatch `database.engine`/`SessionLocal` + `dependency_overrides[get_db]` (pattern `test_documents_api.py`/`test_mail_api_read.py`); i mock su `email_links.gmail.*`.
- `GET /acquisitions/api/list` (esistente) ritorna le trattative: verificare la forma della risposta al momento del wiring di `mfMailAssign` e adattare l'accesso (`d.acquisitions`/array) — il codice fornito prova più forme in modo difensivo.
- `mfEmailExtract` dipende dal copilot presente sulla pagina `/acquisitions` (lo è, via `base.html`). Su `/mail` non c'è tab Email, quindi l'estrazione parte solo dal tab trattativa (per design).
