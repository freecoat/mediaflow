# Fase D — Documenti Drive collegati — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collegare file Google Drive a progetti e trattative (acquisitions) salvando solo un riferimento (metadata + link), via incolla-link e Google Picker, senza storage locale.

**Architecture:** `DocumentLink` (tabella tenant-scoped soft-delete) + servizio `google_drive.py` (parse URL + fetch metadata best-effort, unico `_drive_request` mockabile) + router `documents.py` (link url/picker, list, delete, picker-config, RBAC runtime per `linked_type`) + frontend `documents.js` (lista/add/remove, degrado grazioso Picker) embeddato in `project_detail.html` e `acquisitions.html`.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, urllib.request, vanilla JS, Google Drive v3 REST + Google Picker (CDN), i18n client-side.

## Global Constraints

- **Ramo:** `feat/calendar-phaseB` (contiene A/B/C; Fase D è l'ultima). Nessun push finché Matteo non fa smoke.
- **Nessuna nuova dipendenza Python.** HTTP via `urllib.request` (come `google_calendar.py`/`oauth_providers.py`). Unico helper `_drive_request` = punto di mock.
- **Token:** `get_valid_access_token(db, user_id, "google") -> Optional[str]` (auto-refresh, non committa) e `get_token(db, user_id, "google") -> Optional[UserOAuthToken]` da `app.services.oauth_providers`.
- **Scope:** `drive.file` (già concesso in Fase A). Vede solo file creati/aperti dall'app → incolla-link di file mai toccati può dare 403/404 → metadata `None` → fallback name.
- **Tenant:** `CURRENT_TENANT = 1` in cima al router; ogni query tenant-scoped via `app.services.tenant_guard.scoped`/`fetch_or_404`.
- **RBAC:** riuso permessi esistenti (nessun permesso nuovo). Mapping per `linked_type`: `project` → view `view_projects`, manage `edit_projects`; `acquisition` → view `view_acquisitions`, manage `manage_acquisitions`. Check runtime via `has_permission(user, perm)` (`app.services.rbac`).
- **current_user:** `current_user(request) -> User` (solleva 401 se assente), `current_user_optional(request) -> Optional[User]` da `app.services.rbac`.
- **Form-based** per scrittura (`Form(...)`), **i18n 5 lingue** (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`, **cache-buster** `?v={app_version}` su JS nuovo. Helper globali (`escapeHtml`,`api`,`toast`) da `global.js`, non ridefiniti. No `JSON.stringify` in onclick → `data-*`. `mfT(key)` 1-arg (chiavi sempre definite).
- **Sicurezza:** `web_url` aperto solo se schema `http(s)`, `target="_blank" rel="noopener noreferrer"`. Nel Picker si espone al client solo l'`access_token` effimero (mai il refresh, che resta cifrato server-side).
- **Config Picker:** `GOOGLE_PICKER_API_KEY` letto via `os.getenv("GOOGLE_PICKER_API_KEY", "")` (coerente con `oauth_providers` che legge `GOOGLE_OAUTH_CLIENT_ID` da env). `app_id` = prefisso numerico di `GOOGLE_OAUTH_CLIENT_ID` (parte prima di `-`).
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (heredoc bloccato da hook; usare `printf` in bash).
- **Versione:** `3.5.0-alpha.172.242` → `.243` (Task 5).
- **Smoke server:** uvicorn SENZA reload per evitare figli orfani sul socket: `.venv/Scripts/python.exe -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, log_level='warning')"`. NON `APP_ENV=production` (scatta `assert_production_security`). Usare `127.0.0.1`.

---

### Task 1: Modello `DocumentLink` + migrazione

**Files:**
- Modify: `app/models/models.py` (nuova classe dopo `CalendarEvent`, ~riga 4886)
- Create: `scripts/migrate_documents.py`
- Test: `tests/test_document_link_model.py`

**Interfaces:**
- Produces: `DocumentLink` (tabella `document_links`) con colonne: `id, tenant_id, provider, external_file_id, name, mime_type, web_url, icon_url, owner_email, project_id, acquisition_id, activity_id, client_id, added_by, created_at, is_active`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_document_link_model.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, DocumentLink


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_document_link_columns():
    cols = {c.name for c in DocumentLink.__table__.columns}
    assert {"id", "tenant_id", "provider", "external_file_id", "name", "mime_type",
            "web_url", "icon_url", "owner_email", "project_id", "acquisition_id",
            "activity_id", "client_id", "added_by", "created_at", "is_active"} <= cols


def test_document_link_defaults():
    s = _session()
    d = DocumentLink(tenant_id=1, external_file_id="abc", name="Doc",
                     web_url="https://drive.google.com/file/d/abc/view", project_id=5)
    s.add(d); s.commit(); s.refresh(d)
    assert d.provider == "google"
    assert d.is_active is True
    assert d.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_document_link_model.py -v`
Expected: FAIL (`ImportError: cannot import name 'DocumentLink'`).

- [ ] **Step 3: Add the model**

In `app/models/models.py`, subito dopo la classe `CalendarEvent` (dopo ~riga 4886):

```python
class DocumentLink(Base):
    """Riferimento a un file Google Drive collegato a un'entità (Fase D).
    Nessuno storage locale: si salva solo metadata + link. Tenant-scoped, soft-delete."""
    __tablename__ = "document_links"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    provider: Mapped[str] = mapped_column(String(20), default="google", nullable=False)
    external_file_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    web_url: Mapped[str] = mapped_column(String(1000))
    icon_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Link espliciti nullable (almeno uno valorizzato — validato nel router)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    acquisition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("acquisitions.id"), nullable=True, index=True)
    activity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("activities.id"), nullable=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    added_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_document_link_model.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Create migration script**

```python
# scripts/migrate_documents.py
"""Migrazione Fase D — tabella document_links (idempotente).

La tabella è creata anche da Base.metadata.create_all() al boot; questo script
serve per DB esistenti dove si preferisce una migrazione esplicita + verifica.
Uso: .venv/Scripts/python.exe scripts/migrate_documents.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect
from app.database import engine
from app.models.models import Base, DocumentLink  # noqa: F401


def main():
    insp = inspect(engine)
    if "document_links" in insp.get_table_names():
        print("[migrate_documents] tabella document_links già presente — nessuna azione.")
        return
    DocumentLink.__table__.create(bind=engine)
    print("[migrate_documents] tabella document_links creata.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run migration script (smoke)**

Run: `.venv/Scripts/python.exe scripts/migrate_documents.py`
Expected: stampa "creata" o "già presente" senza traceback.

- [ ] **Step 7: Commit**

```bash
git add app/models/models.py scripts/migrate_documents.py tests/test_document_link_model.py
git commit -F <msgfile>
# "feat(documents): modello DocumentLink + migrazione idempotente"
```

---

### Task 2: `google_drive.py` — parse URL + metadata best-effort

**Files:**
- Create: `app/services/google_drive.py`
- Test: `tests/test_google_drive.py`

**Interfaces:**
- Consumes: `get_valid_access_token`, `get_token` (oauth_providers).
- Produces:
  - `parse_drive_file_id(url: str) -> Optional[str]`
  - `_drive_request(method, url, token, params=None) -> dict` (mock point)
  - `fetch_file_metadata(db, user_id, file_id) -> Optional[dict]` → `{file_id, name, mime_type, web_url, icon_url, owner_email}` o `None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_google_drive.py
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
from app.services import google_drive as gd


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
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def test_parse_file_url():
    assert gd.parse_drive_file_id("https://drive.google.com/file/d/ABC123/view?usp=sharing") == "ABC123"


def test_parse_docs_url():
    assert gd.parse_drive_file_id("https://docs.google.com/document/d/XYZ_9/edit") == "XYZ_9"


def test_parse_sheets_url():
    assert gd.parse_drive_file_id("https://docs.google.com/spreadsheets/d/SHEET1/edit#gid=0") == "SHEET1"


def test_parse_open_id_url():
    assert gd.parse_drive_file_id("https://drive.google.com/open?id=OID42") == "OID42"


def test_parse_uc_id_url():
    assert gd.parse_drive_file_id("https://drive.google.com/uc?id=UC7&export=download") == "UC7"


def test_parse_non_drive_url_none():
    assert gd.parse_drive_file_id("https://example.com/foo") is None


def test_fetch_metadata_ok(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gd, "_drive_request", lambda m, u, t, params=None: {
        "id": "ABC", "name": "Contratto.pdf", "mimeType": "application/pdf",
        "webViewLink": "https://drive.google.com/file/d/ABC/view",
        "iconLink": "https://ssl.gstatic.com/pdf.png",
        "owners": [{"emailAddress": "owner@x.com"}]})
    md = gd.fetch_file_metadata(s, 1, "ABC")
    assert md["file_id"] == "ABC"
    assert md["name"] == "Contratto.pdf"
    assert md["mime_type"] == "application/pdf"
    assert md["web_url"].endswith("/view")
    assert md["owner_email"] == "owner@x.com"


def test_fetch_metadata_none_without_token():
    s = _session()  # nessun token
    assert gd.fetch_file_metadata(s, 1, "ABC") is None


def test_fetch_metadata_best_effort_on_error(monkeypatch):
    s = _session(); _connect(s)
    def boom(*a, **k): raise RuntimeError("HTTP 403: Forbidden")
    monkeypatch.setattr(gd, "_drive_request", boom)
    assert gd.fetch_file_metadata(s, 1, "ABC") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_drive.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.google_drive`).

- [ ] **Step 3: Create `google_drive.py`**

```python
# app/services/google_drive.py
"""Google Drive API client — Fase D (v3.5.0-alpha.172.243).

Layer HTTP isolato (urllib, coerente con google_calendar.py). Unico
`_drive_request` = punto di mock nei test. Scope: drive.file (vede solo i file
creati/aperti dall'app; un URL incollato mai toccato può dare 403/404 →
metadata None → il router usa un fallback name)."""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional

from sqlalchemy.orm import Session

from app.services.oauth_providers import get_valid_access_token

log = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/drive/v3"
_META_FIELDS = "id,name,mimeType,webViewLink,iconLink,owners"

# Varianti URL Drive/Docs/Sheets/Slides
_PATTERNS = [
    re.compile(r"/(?:file|document|spreadsheets|presentation|drawings)/d/([A-Za-z0-9_-]+)"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]+)"),
]


def parse_drive_file_id(url: str) -> Optional[str]:
    if not url:
        return None
    for pat in _PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def _drive_request(method: str, url: str, token: str, params=None) -> dict:
    """Chiamata HTTP all'API Drive. Ritorna dict JSON (o {} se vuoto).
    Punto unico di mock. Solleva urllib.error.HTTPError su status >=400."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method=method, headers={
        "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def fetch_file_metadata(db: Session, user_id: int, file_id: str) -> Optional[dict]:
    """Metadata di un file Drive. Best-effort: token assente/403/404/rete → None."""
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    try:
        res = _drive_request("GET", _API_BASE + "/files/" + urllib.parse.quote(file_id),
                             token, params={"fields": _META_FIELDS}) or {}
    except Exception as e:
        log.warning(f"fetch_file_metadata fallita file={file_id} user={user_id}: {e}")
        return None
    owners = res.get("owners") or []
    owner_email = owners[0].get("emailAddress") if owners else None
    return {
        "file_id": res.get("id") or file_id,
        "name": res.get("name") or "",
        "mime_type": res.get("mimeType"),
        "web_url": res.get("webViewLink") or "",
        "icon_url": res.get("iconLink"),
        "owner_email": owner_email,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_drive.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/google_drive.py tests/test_google_drive.py
git commit -F <msgfile>
# "feat(documents): google_drive.py — parse URL + metadata best-effort"
```

---

### Task 3: Router `documents.py` — link/list/delete/picker-config + registrazione

**Files:**
- Create: `app/routers/documents.py`
- Modify: `app/main.py` (import + `include_router`, ~riga 2841 vicino a `calendar_router`)
- Test: `tests/test_documents_api.py`

**Interfaces:**
- Consumes: `parse_drive_file_id`, `fetch_file_metadata` (Task 2); `DocumentLink` (Task 1); `has_permission`, `current_user`, `current_user_optional` (rbac); `scoped`, `fetch_or_404` (tenant_guard); `get_valid_access_token`, `get_token` (oauth_providers); `Project`, `Acquisition` (models).
- Produces:
  - `POST /documents/api/link` (Form: `linked_type`, `linked_id`, opz `url`, opz `file_id/name/mime_type/web_url/icon_url`) → DocumentLink serializzato.
  - `GET /documents/api/list?linked_type&linked_id` → `{"documents": [...]}`.
  - `DELETE /documents/api/link/{id}` → `{"ok": True}`.
  - `GET /documents/api/picker-config` → `{"enabled": bool, "api_key"?, "app_id"?, "oauth_token"?}`.
  - `_serialize_doc(d) -> dict`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_documents_api.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import get_db
from app.models.models import Base, Tenant, User, UserRole, Project, Client
from app.services import rbac


@pytest.fixture
def client(monkeypatch):
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    TestingSession = sessionmaker(bind=e, expire_on_commit=False, future=True)
    s = TestingSession()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    admin = User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
                 hashed_password="x", role=UserRole.admin, is_active=True)
    s.add(admin)
    s.add(Client(id=1, tenant_id=1, name="Cliente", is_active=True))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1, is_active=True))
    s.commit()

    def _get_db():
        try:
            yield s
        finally:
            pass
    app.dependency_overrides[get_db] = _get_db
    # documents.py fa `from app.services.rbac import current_user, ...`: i nomi sono
    # legati NEL modulo documents → l'override va fatto su app.routers.documents.*
    # (monkeypatch, non assegnazione diretta: ripristino automatico a fine test).
    import app.routers.documents as docmod
    monkeypatch.setattr(docmod, "current_user", lambda request=None: admin)
    monkeypatch.setattr(docmod, "current_user_optional", lambda request=None: admin)
    c = TestClient(app)
    yield c, s
    app.dependency_overrides.clear()


def test_link_by_url(client, monkeypatch):
    c, s = client
    from app.services import google_drive as gd
    monkeypatch.setattr(gd, "parse_drive_file_id", lambda u: "ABC")
    monkeypatch.setattr(gd, "fetch_file_metadata", lambda db, uid, fid: {
        "file_id": "ABC", "name": "Contratto.pdf", "mime_type": "application/pdf",
        "web_url": "https://drive.google.com/file/d/ABC/view",
        "icon_url": "https://icon", "owner_email": "o@x.com"})
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "url": "https://drive.google.com/file/d/ABC/view"})
    assert r.status_code == 200
    b = r.json()
    assert b["name"] == "Contratto.pdf"
    assert b["external_file_id"] == "ABC"


def test_link_by_url_non_drive_400(client, monkeypatch):
    c, s = client
    from app.services import google_drive as gd
    monkeypatch.setattr(gd, "parse_drive_file_id", lambda u: None)
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "url": "https://example.com/x"})
    assert r.status_code == 400


def test_link_by_url_fallback_name(client, monkeypatch):
    c, s = client
    from app.services import google_drive as gd
    monkeypatch.setattr(gd, "parse_drive_file_id", lambda u: "ZZZ")
    monkeypatch.setattr(gd, "fetch_file_metadata", lambda db, uid, fid: None)  # 403/non accessibile
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "url": "https://drive.google.com/file/d/ZZZ/view"})
    assert r.status_code == 200
    assert r.json()["name"]  # fallback non vuoto
    assert r.json()["external_file_id"] == "ZZZ"


def test_link_by_picker_payload(client):
    c, s = client
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "file_id": "PICK1", "name": "Slide.pptx", "mime_type": "x",
               "web_url": "https://drive.google.com/file/d/PICK1/view", "icon_url": "https://i"})
    assert r.status_code == 200
    assert r.json()["external_file_id"] == "PICK1"


def test_list_filtered(client):
    c, s = client
    c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
           "file_id": "F1", "name": "A", "web_url": "https://drive.google.com/file/d/F1/view"})
    r = c.get("/documents/api/list", params={"linked_type": "project", "linked_id": "1"})
    assert r.status_code == 200
    assert len(r.json()["documents"]) == 1


def test_delete_soft(client):
    c, s = client
    lid = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
                 "file_id": "F2", "name": "B", "web_url": "https://drive.google.com/file/d/F2/view"}).json()["id"]
    r = c.delete(f"/documents/api/link/{lid}")
    assert r.status_code == 200
    r2 = c.get("/documents/api/list", params={"linked_type": "project", "linked_id": "1"})
    assert all(d["id"] != lid for d in r2.json()["documents"])


def test_linked_entity_404(client):
    c, s = client
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "999",
               "file_id": "F3", "name": "C", "web_url": "https://drive.google.com/file/d/F3/view"})
    assert r.status_code == 404


def test_picker_config_disabled_without_key(client, monkeypatch):
    c, s = client
    monkeypatch.delenv("GOOGLE_PICKER_API_KEY", raising=False)
    r = c.get("/documents/api/picker-config")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_documents_api.py -v`
Expected: FAIL (404 su tutti gli endpoint — router assente).

- [ ] **Step 3: Create `documents.py`**

```python
# app/routers/documents.py
"""Router documenti collegati — Fase D (v3.5.0-alpha.172.243).

Collega file Google Drive a progetti/acquisitions via incolla-link o Picker,
salvando solo un riferimento (metadata + link). Tenant-scoped, soft-delete,
RBAC runtime per linked_type. Best-effort: metadata assenti → fallback name."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import DocumentLink, Project, Acquisition
from app.services.rbac import has_permission, current_user, current_user_optional
from app.services.tenant_guard import scoped, fetch_or_404
from app.services import google_drive
from app.services.oauth_providers import get_valid_access_token, get_token

router = APIRouter(tags=["documents"])

CURRENT_TENANT = 1

# linked_type → (modello, perm_view, perm_manage)
_ENTITY = {
    "project": (Project, "view_projects", "edit_projects"),
    "acquisition": (Acquisition, "view_acquisitions", "manage_acquisitions"),
}


def _serialize_doc(d: DocumentLink) -> dict:
    return {
        "id": d.id, "provider": d.provider, "external_file_id": d.external_file_id,
        "name": d.name, "mime_type": d.mime_type, "web_url": d.web_url,
        "icon_url": d.icon_url, "owner_email": d.owner_email,
        "project_id": d.project_id, "acquisition_id": d.acquisition_id,
    }


def _resolve_entity(linked_type: str):
    ent = _ENTITY.get(linked_type)
    if not ent:
        raise HTTPException(400, f"linked_type non valido: {linked_type}")
    return ent


def _safe_url(u: Optional[str]) -> str:
    u = (u or "").strip()
    return u if u.lower().startswith(("http://", "https://")) else ""


@router.post("/documents/api/link")
async def link_document(request: Request, db: Session = Depends(get_db),
                        linked_type: str = Form(...), linked_id: int = Form(...),
                        url: Optional[str] = Form(None),
                        file_id: Optional[str] = Form(None),
                        name: Optional[str] = Form(None),
                        mime_type: Optional[str] = Form(None),
                        web_url: Optional[str] = Form(None),
                        icon_url: Optional[str] = Form(None)):
    user = current_user(request)
    model, _pv, perm_manage = _resolve_entity(linked_type)
    if not has_permission(user, perm_manage):
        raise HTTPException(403, "Permesso negato")
    # entità esiste + tenant-scoped
    fetch_or_404(db, model, linked_id, tenant_id=CURRENT_TENANT)

    fid = (file_id or "").strip()
    d_name = (name or "").strip()
    d_web = _safe_url(web_url)
    d_mime = mime_type
    d_icon = icon_url
    d_owner = None

    if not fid:  # modo incolla-link
        parsed = google_drive.parse_drive_file_id(url or "")
        if not parsed:
            raise HTTPException(400, "URL Drive non riconosciuto")
        fid = parsed
        md = google_drive.fetch_file_metadata(db, user.id, fid)
        if md:
            d_name = md["name"] or d_name
            d_mime = md["mime_type"]
            d_web = _safe_url(md["web_url"]) or _safe_url(url)
            d_icon = md["icon_url"]
            d_owner = md["owner_email"]
        else:  # fallback: file non accessibile via drive.file
            d_web = _safe_url(url)
            d_name = d_name or "Documento Drive"
    if not d_name:
        d_name = "Documento Drive"
    if not d_web:
        d_web = "https://drive.google.com/file/d/" + fid + "/view"

    doc = DocumentLink(tenant_id=CURRENT_TENANT, provider="google", external_file_id=fid,
                       name=d_name, mime_type=d_mime, web_url=d_web, icon_url=d_icon,
                       owner_email=d_owner, added_by=user.id)
    setattr(doc, f"{linked_type}_id", linked_id)
    db.add(doc); db.commit(); db.refresh(doc)
    return _serialize_doc(doc)


@router.get("/documents/api/list")
async def list_documents(request: Request, linked_type: str, linked_id: int,
                         db: Session = Depends(get_db)):
    user = current_user(request)
    _model, perm_view, _pm = _resolve_entity(linked_type)
    if not has_permission(user, perm_view):
        raise HTTPException(403, "Permesso negato")
    q = scoped(db.query(DocumentLink), DocumentLink).filter(
        getattr(DocumentLink, f"{linked_type}_id") == linked_id,
        DocumentLink.is_active == True,  # noqa: E712
    ).order_by(DocumentLink.created_at.desc())
    return {"documents": [_serialize_doc(d) for d in q.all()]}


@router.delete("/documents/api/link/{doc_id}")
async def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    doc = fetch_or_404(db, DocumentLink, doc_id, tenant_id=CURRENT_TENANT)
    linked_type = ("project" if doc.project_id else "acquisition" if doc.acquisition_id
                   else "project")
    _model, _pv, perm_manage = _resolve_entity(linked_type)
    if not has_permission(user, perm_manage):
        raise HTTPException(403, "Permesso negato")
    doc.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/documents/api/picker-config")
async def picker_config(request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    api_key = os.getenv("GOOGLE_PICKER_API_KEY", "").strip()
    if not user or not api_key:
        return {"enabled": False}
    token = get_valid_access_token(db, user.id, "google")
    if not token:
        return {"enabled": False}
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    app_id = client_id.split("-", 1)[0] if "-" in client_id else client_id
    return {"enabled": True, "api_key": api_key, "app_id": app_id, "oauth_token": token}
```

- [ ] **Step 4: Register the router in `main.py`**

In `app/main.py`, vicino all'import di `calendar_router` (cerca `import ... calendar` in cima) aggiungi l'import; poi dopo `app.include_router(calendar_router.router)` (~riga 2841):

```python
from app.routers import documents as documents_router  # (in cima, con gli altri import router)
```
```python
app.include_router(documents_router.router)  # Fase D — documenti Drive collegati
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_documents_api.py -v`
Expected: PASS (8 passed).

- [ ] **Step 6: Commit**

```bash
git add app/routers/documents.py app/main.py tests/test_documents_api.py
git commit -F <msgfile>
# "feat(documents): router link/list/delete/picker-config + registrazione"
```

---

### Task 4: Frontend — `documents.js` + embed progetto/acquisition + i18n

**Files:**
- Create: `app/static/js/documents.js`
- Modify: `app/templates/pages/project_detail.html` (sezione 📎 + include script)
- Modify: `app/templates/pages/acquisitions.html` (sezione 📎 nel detail-panel + include script)
- Modify: `app/static/js/i18n.js` (chiavi `doc.*`)
- Test: `tests/test_documents_page.py`

**Interfaces:**
- Consumes: endpoint Task 3; helper globali `escapeHtml`, `toast`, `mfT` (global.js/i18n.js).
- Produces: funzioni globali `mfDocInit(linkedType, linkedId)`, `mfDocList(linkedType, linkedId)`, `mfDocAddByUrl(linkedType, linkedId)`, `mfDocPicker(linkedType, linkedId)`; container id `doc-list-{linkedType}`, input id `doc-url-{linkedType}`, bottone Picker id `doc-pick-{linkedType}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_documents_page.py
import pathlib


def test_project_detail_has_doc_section():
    html = pathlib.Path("app/templates/pages/project_detail.html").read_text(encoding="utf-8")
    assert 'doc-list-project' in html
    assert 'documents.js' in html


def test_acquisitions_has_doc_section():
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert 'doc-list-acquisition' in html
    assert 'documents.js' in html


def test_i18n_has_doc_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("doc.section", "doc.addByUrl", "doc.urlPlaceholder", "doc.pick",
                "doc.empty", "doc.remove", "doc.added", "doc.error", "doc.invalidUrl"):
        assert key in src, key


def test_documents_js_defines_globals():
    src = pathlib.Path("app/static/js/documents.js").read_text(encoding="utf-8")
    for fn in ("mfDocInit", "mfDocList", "mfDocAddByUrl", "mfDocPicker"):
        assert fn in src, fn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_documents_page.py -v`
Expected: FAIL (file/chiavi assenti).

- [ ] **Step 3: Add i18n keys**

In `app/static/js/i18n.js`, vicino alle altre chiavi di sezione (es. dopo le `cal.*`):

```javascript
  'doc.section':       {it: 'Documenti', en: 'Documents', fr: 'Documents', de: 'Dokumente', es: 'Documentos'},
  'doc.addByUrl':      {it: 'Aggiungi da link', en: 'Add by link', fr: 'Ajouter par lien', de: 'Per Link hinzufügen', es: 'Añadir por enlace'},
  'doc.urlPlaceholder': {it: 'Incolla link Google Drive…', en: 'Paste Google Drive link…', fr: 'Collez le lien Google Drive…', de: 'Google-Drive-Link einfügen…', es: 'Pega el enlace de Google Drive…'},
  'doc.pick':          {it: 'Scegli da Drive', en: 'Pick from Drive', fr: 'Choisir depuis Drive', de: 'Aus Drive wählen', es: 'Elegir de Drive'},
  'doc.empty':         {it: 'Nessun documento collegato', en: 'No linked documents', fr: 'Aucun document lié', de: 'Keine verknüpften Dokumente', es: 'Ningún documento vinculado'},
  'doc.remove':        {it: 'Rimuovi', en: 'Remove', fr: 'Retirer', de: 'Entfernen', es: 'Quitar'},
  'doc.added':         {it: 'Documento collegato', en: 'Document linked', fr: 'Document lié', de: 'Dokument verknüpft', es: 'Documento vinculado'},
  'doc.error':         {it: 'Errore documento', en: 'Document error', fr: 'Erreur document', de: 'Dokumentfehler', es: 'Error de documento'},
  'doc.invalidUrl':    {it: 'Link Drive non valido', en: 'Invalid Drive link', fr: 'Lien Drive invalide', de: 'Ungültiger Drive-Link', es: 'Enlace de Drive no válido'},
```

- [ ] **Step 4: Create `documents.js`**

```javascript
// app/static/js/documents.js — Fase D: documenti Drive collegati (progetto/acquisition)
async function mfDocList(linkedType, linkedId) {
  const box = document.getElementById('doc-list-' + linkedType);
  if (!box) return;
  try {
    const r = await fetch('/documents/api/list?linked_type=' + encodeURIComponent(linkedType) +
      '&linked_id=' + encodeURIComponent(linkedId));
    const d = await r.json();
    const docs = d.documents || [];
    if (!docs.length) { box.innerHTML = '<div class="muted" data-i18n="doc.empty">' + mfT('doc.empty') + '</div>'; return; }
    box.innerHTML = docs.map(function (doc) {
      const icon = doc.icon_url ? '<img src="' + escapeHtml(doc.icon_url) + '" width="16" height="16" alt="">' : '📄';
      const owner = doc.owner_email ? '<span class="muted"> · ' + escapeHtml(doc.owner_email) + '</span>' : '';
      const safe = /^https?:\/\//i.test(doc.web_url || '') ? doc.web_url : '#';
      return '<div class="doc-row">' + icon +
        ' <a href="' + escapeHtml(safe) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(doc.name) + '</a>' +
        owner +
        ' <button class="btn-icon" title="' + mfT('doc.remove') + '" data-doc-remove="' + doc.id +
        '" data-doc-type="' + escapeHtml(linkedType) + '" data-doc-linked="' + escapeHtml(String(linkedId)) + '">🗑</button></div>';
    }).join('');
  } catch (e) { box.innerHTML = '<div class="muted">' + mfT('doc.error') + '</div>'; }
}

async function mfDocAddByUrl(linkedType, linkedId) {
  const inp = document.getElementById('doc-url-' + linkedType);
  if (!inp || !inp.value.trim()) return;
  const fd = new FormData();
  fd.append('linked_type', linkedType);
  fd.append('linked_id', linkedId);
  fd.append('url', inp.value.trim());
  try {
    const r = await fetch('/documents/api/link', { method: 'POST', body: fd });
    if (r.ok) { inp.value = ''; if (window.toast) toast(mfT('doc.added'), 'success'); mfDocList(linkedType, linkedId); }
    else if (r.status === 400) { if (window.toast) toast(mfT('doc.invalidUrl'), 'error'); }
    else { if (window.toast) toast(mfT('doc.error'), 'error'); }
  } catch (e) { if (window.toast) toast(mfT('doc.error'), 'error'); }
}

async function mfDocRemove(docId, linkedType, linkedId) {
  try {
    const r = await fetch('/documents/api/link/' + docId, { method: 'DELETE' });
    if (r.ok) mfDocList(linkedType, linkedId);
  } catch (e) { if (window.toast) toast(mfT('doc.error'), 'error'); }
}

async function mfDocPicker(linkedType, linkedId) {
  try {
    const cfg = await (await fetch('/documents/api/picker-config')).json();
    if (!cfg.enabled) return;
    await new Promise(function (res) { gapi.load('picker', { callback: res }); });
    const view = new google.picker.DocsView(google.picker.ViewId.DOCS).setIncludeFolders(true);
    const picker = new google.picker.PickerBuilder()
      .setOAuthToken(cfg.oauth_token).setDeveloperKey(cfg.api_key).setAppId(cfg.app_id)
      .addView(view)
      .setCallback(function (data) {
        if (data.action !== google.picker.Action.PICKED) return;
        const f = data.docs[0];
        const fd = new FormData();
        fd.append('linked_type', linkedType); fd.append('linked_id', linkedId);
        fd.append('file_id', f.id); fd.append('name', f.name || '');
        fd.append('mime_type', f.mimeType || '');
        fd.append('web_url', f.url || ('https://drive.google.com/file/d/' + f.id + '/view'));
        fd.append('icon_url', (f.iconUrl || ''));
        fetch('/documents/api/link', { method: 'POST', body: fd }).then(function (r) {
          if (r.ok) { if (window.toast) toast(mfT('doc.added'), 'success'); mfDocList(linkedType, linkedId); }
        });
      }).build();
    picker.setVisible(true);
  } catch (e) { if (window.toast) toast(mfT('doc.error'), 'error'); }
}

async function mfDocInit(linkedType, linkedId) {
  // click handler rimozione (delegato)
  document.addEventListener('click', function (ev) {
    const b = ev.target.closest && ev.target.closest('[data-doc-remove]');
    if (!b) return;
    mfDocRemove(b.getAttribute('data-doc-remove'), b.getAttribute('data-doc-type'),
                b.getAttribute('data-doc-linked'));
  });
  // mostra bottone Picker solo se abilitato + carica gapi CDN
  try {
    const cfg = await (await fetch('/documents/api/picker-config')).json();
    const btn = document.getElementById('doc-pick-' + linkedType);
    if (btn && cfg.enabled) {
      btn.style.display = '';
      if (!window.gapi) {
        const sc = document.createElement('script');
        sc.src = 'https://apis.google.com/js/api.js'; document.head.appendChild(sc);
      }
    }
  } catch (e) { /* picker best-effort */ }
  mfDocList(linkedType, linkedId);
}
```

- [ ] **Step 5: Embed in `project_detail.html`**

Individua una sezione adatta (dopo i metadati progetto). Aggiungi il blocco (adatta le classi a quelle esistenti nella pagina):

```html
<!-- 📎 Documenti collegati (Fase D) -->
<section class="card" id="doc-section-project">
  <h3>📎 <span data-i18n="doc.section">Documenti</span></h3>
  <div id="doc-list-project" class="doc-list"></div>
  <div class="doc-add">
    <input type="url" id="doc-url-project" class="input" data-i18n-attr="placeholder" data-i18n="doc.urlPlaceholder" placeholder="Incolla link Google Drive…">
    <button class="btn btn-secondary" onclick="mfDocAddByUrl('project', {{ project.id }})" data-i18n="doc.addByUrl">Aggiungi da link</button>
    <button class="btn btn-secondary" id="doc-pick-project" style="display:none" onclick="mfDocPicker('project', {{ project.id }})" data-i18n="doc.pick">Scegli da Drive</button>
  </div>
</section>
<script src="/static/js/documents.js?v={{ app_version }}"></script>
<script>document.addEventListener('DOMContentLoaded', function(){ mfDocInit('project', {{ project.id }}); });</script>
```

- [ ] **Step 6: Embed in `acquisitions.html`**

Nel markup del detail-panel della trattativa (vicino alla tab/lista Appuntamenti già presente), aggiungi la stessa sezione con `linked_type='acquisition'`. L'id dell'acquisizione selezionata è disponibile via la variabile JS del pannello (usa il pattern già in uso nel file, es. `_selAcqId`); se il rendering è client-side, monta la sezione quando si apre il dettaglio chiamando `mfDocInit('acquisition', id)`:

```html
<!-- 📎 Documenti collegati (Fase D) -->
<div class="acq-docs">
  <h4>📎 <span data-i18n="doc.section">Documenti</span></h4>
  <div id="doc-list-acquisition" class="doc-list"></div>
  <div class="doc-add">
    <input type="url" id="doc-url-acquisition" class="input" data-i18n-attr="placeholder" data-i18n="doc.urlPlaceholder" placeholder="Incolla link Google Drive…">
    <button class="btn btn-secondary" id="acq-doc-add" data-i18n="doc.addByUrl">Aggiungi da link</button>
    <button class="btn btn-secondary" id="doc-pick-acquisition" style="display:none" data-i18n="doc.pick">Scegli da Drive</button>
  </div>
</div>
<script src="/static/js/documents.js?v={{ app_version }}"></script>
```

E nel JS del pannello, quando si apre il dettaglio di una trattativa con id `aid`:

```javascript
  document.getElementById('acq-doc-add').onclick = function () { mfDocAddByUrl('acquisition', aid); };
  document.getElementById('doc-pick-acquisition').onclick = function () { mfDocPicker('acquisition', aid); };
  mfDocInit('acquisition', aid);
```

- [ ] **Step 7: Run test + JS syntax + grep guard**

Run: `.venv/Scripts/python.exe -m pytest tests/test_documents_page.py -v`
Expected: PASS (4 passed).
Run: `node --check app/static/js/documents.js`
Expected: nessun errore.
Run: `node --check app/static/js/i18n.js`
Expected: nessun errore.

- [ ] **Step 8: Commit**

```bash
git add app/static/js/documents.js app/static/js/i18n.js app/templates/pages/project_detail.html app/templates/pages/acquisitions.html tests/test_documents_page.py
git commit -F <msgfile>
# "feat(documents): frontend documents.js + embed progetto/acquisition + i18n"
```

---

### Task 5: Chiusura fase — config + strumenti + bump + suite + smoke

**Files:**
- Modify: `app/main.py` (`.242` → `.243`), `.env.example`, `strumenti.bat`, `strumenti.sh`, `CHANGELOG.md`, `docs/STATO.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: versione `3.5.0-alpha.172.243`.

- [ ] **Step 1: `.env.example` — variabile Picker**

Aggiungi (vicino a `GOOGLE_OAUTH_CLIENT_ID`):

```
# Fase D — Google Picker (opzionale). Senza questa chiave l'incolla-link funziona comunque; il bottone "Scegli da Drive" resta nascosto.
GOOGLE_PICKER_API_KEY=
```

- [ ] **Step 2: `strumenti.bat` / `strumenti.sh` — voce migrazione documenti**

Aggiungi una voce che esegue `.venv/Scripts/python.exe scripts/migrate_documents.py` (bat) e l'equivalente `python scripts/migrate_documents.py` (sh), seguendo il pattern delle voci di migrazione esistenti (es. `migrate_calendar_events.py`). Etichetta: "Migra Fase D — documenti Drive".

- [ ] **Step 3: Bump version**

In `app/main.py`: `version="3.5.0-alpha.172.242"` → `"3.5.0-alpha.172.243"`.

- [ ] **Step 4: CHANGELOG**

In `CHANGELOG.md`, nuova voce in cima:

```markdown
## v3.5.0-alpha.172.243 — Fase D Calendario/Account: documenti Drive collegati (6 lug 2026)

- **DocumentLink** (`document_links`, tenant-scoped, soft-delete): collega file Google Drive a **progetti** e **trattative** salvando solo un riferimento (metadata + link), nessuno storage locale.
- **Due modi di aggancio**: incolla-link (sempre attivo → parse URL Drive + fetch metadata `drive.file` best-effort) e **Google Picker** (bottone "Scegli da Drive" visibile solo se `GOOGLE_PICKER_API_KEY` configurato + utente Google connesso).
- **Servizio** `app/services/google_drive.py` (urllib, `_drive_request` mockabile) + **router** `app/routers/documents.py` (link/list/delete/picker-config, RBAC runtime per `linked_type`, tenant-scope). Sezione **📎 Documenti** nel detail di progetto e acquisition.
- **Best-effort**: `drive.file` vede solo file creati/aperti dall'app → incolla-link di file mai toccati → metadata `None` → fallback name; il Picker aggira (l'atto di scegliere concede l'accesso). Nessun refresh token verso il client (solo access_token effimero per il Picker).
- Migrazione `scripts/migrate_documents.py` (tabella creata anche da create_all al boot) + voce strumenti. i18n 5 lingue (`doc.*`). Config `GOOGLE_PICKER_API_KEY` in `.env.example`. **Chiude il programma A/B/C/D** (account linking + calendario + documenti).
```

- [ ] **Step 5: STATO**

In `docs/STATO.md`: versione corrente → `.243`; sezione `### α.172.243 ✅ (Fase D — documenti Drive — 6 lug)` coi punti sopra; **Prossimo step** → merge `feat/calendar-phaseB` → main + push dopo smoke Matteo (prereq: OAuth client Google Cloud + eventuale `GOOGLE_PICKER_API_KEY` per il Picker). Programma A/B/C/D chiuso.

- [ ] **Step 6: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (1072 + ~23 nuovi). Se un test preesistente rompe, correggilo minimamente e annota.

- [ ] **Step 7: Smoke browser (uvicorn senza reload)**

Avvia: `.venv/Scripts/python.exe -c "import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port=8000, log_level='warning')"` (background). Login `admin@mediaflow.it` / `admin123`. Su un progetto: apri detail → sezione 📎 Documenti presente, incolla un link Drive (`https://drive.google.com/file/d/TEST/view`) → compare in lista (name fallback "Documento Drive" se il file non è accessibile via `drive.file`), 🗑 lo rimuove. Bottone "Scegli da Drive" nascosto senza `GOOGLE_PICKER_API_KEY`. Stessa verifica nel detail di una trattativa. 0 errori console. Chiudi il server (`taskkill //F //IM python.exe` se serve, poi verifica porta libera).

- [ ] **Step 8: Commit**

```bash
git add app/main.py .env.example strumenti.bat strumenti.sh CHANGELOG.md docs/STATO.md
git commit -F <msgfile>
# "chore(documents): Fase D v3.5.0-alpha.172.243 (documenti Drive) — chiude A/B/C/D"
```

---

## Self-Review

**1. Spec coverage:**
- `DocumentLink` (tabella + colonne + link nullable) → Task 1 ✓
- `google_drive.py` (parse URL varianti + fetch metadata best-effort) → Task 2 ✓
- Router `documents.py` (link url/picker, list, delete, picker-config, RBAC runtime, tenant-scope) → Task 3 ✓
- Aggancio entrambi (incolla-link + Picker degrado grazioso) → Task 3 (backend) + Task 4 (frontend) ✓
- Embed 📎 progetto + acquisition → Task 4 ✓
- Fallback name quando metadata None → Task 3 (`link_document`) + test `test_link_by_url_fallback_name` ✓
- Sicurezza web_url http(s) + noopener + solo access_token al client → Task 3 (`_safe_url`, `picker_config`) + Task 4 (regex href) ✓
- Migrazione + auto-create + strumenti → Task 1 + Task 5 ✓
- Config `GOOGLE_PICKER_API_KEY` + .env.example → Task 3 + Task 5 ✓
- i18n 5 lingue → Task 4 ✓
- Bump/CHANGELOG/STATO → Task 5 ✓
- Test (google_drive, documents_api, documents_page) + smoke → Task 2/3/4/5 ✓

**2. Placeholder scan:** nessun TBD/TODO; ogni step di codice mostra il codice. Nota: gli embed Task 4 Step 5/6 richiedono di adattare le classi CSS e il punto d'inserimento ai pattern esistenti di `project_detail.html`/`acquisitions.html` — l'implementatore ispeziona il file e segue lo stile locale (il markup fornito è completo e funzionante, va solo posizionato).

**3. Type consistency:**
- `parse_drive_file_id(url)->Optional[str]`, `fetch_file_metadata(db,user_id,file_id)->Optional[dict]` con chiavi `{file_id,name,mime_type,web_url,icon_url,owner_email}` coerenti tra Task 2 (impl+test) e Task 3 (consumo).
- Router: `linked_type` ∈ {`project`,`acquisition`}; `_ENTITY` mappa a `(model, perm_view, perm_manage)` = (`Project`,`view_projects`,`edit_projects`) / (`Acquisition`,`view_acquisitions`,`manage_acquisitions`) — perm verificati esistenti in `rbac.py`.
- `_serialize_doc` chiavi coerenti con `documents.js` (`name,web_url,icon_url,owner_email,id`).
- Funzioni JS globali `mfDocInit/mfDocList/mfDocAddByUrl/mfDocPicker/mfDocRemove` coerenti Task 4 (impl+test+embed).
- `has_permission(user, perm)`, `current_user(request)`, `fetch_or_404(db, model, id, tenant_id=)`, `scoped(query, model)` — firme verificate nel codebase.

## Note

- La tabella `document_links` è creata da `Base.metadata.create_all()` al boot (create_tables); `migrate_documents.py` è per DB dove si vuole la migrazione esplicita. Nessuna colonna da aggiungere a `_auto_migrate_columns()` (è una tabella nuova, non un ALTER).
- Il test fixture di `test_documents_api.py` bypassa l'auth sovrascrivendo `rbac.current_user`/`current_user_optional` (admin ha tutti i permessi). Verificare che il pattern di override combaci con come `documents.py` importa quei simboli (import `from app.services.rbac import ...`: l'override va fatto sull'attributo del modulo `app.services.rbac`, come nel fixture).
- `acquisitions.html` è a rendering parzialmente client-side: l'esatto punto d'aggancio (`aid`, apertura pannello) va letto dal file in fase di implementazione; il contratto JS (`mfDocInit('acquisition', aid)`) resta invariato.
