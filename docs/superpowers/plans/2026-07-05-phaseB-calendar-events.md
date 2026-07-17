# Fase B — CalendarEvent + Calendario FullCalendar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calendario Claqo nativo sugli appuntamenti — entità `CalendarEvent` generica, pagina `/calendar` con FullCalendar, embed in acquisitions, capability AI — funzionante anche senza account Google collegato.

**Architecture:** Nuova tabella `calendar_events` (tenant-scoped, soft-delete, link espliciti nullable a acquisition/project/activity/client + colonne sync per Fase C). Router `app/routers/calendar.py` CRUD Form-based con permessi RBAC `view_calendar`/`manage_calendar`. Pagina `calendar.html` che estende `base.html` e carica FullCalendar via CDN, alimentata da `GET /calendar/api/events`. Marcatori derivati read-only (`Activity.next_action_date`, `Acquisition.expected_close_date`). Embed nel detail-panel acquisitions come tab "Appuntamenti". Capability AI `propose_calendar_event` nel registry esistente.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (`Mapped`/`mapped_column`), SQLite, Jinja2, vanilla JS, FullCalendar 6 (CDN), i18n client-side.

## Global Constraints

- **Python** 3.11+ (priorità 3.14). Nessuna nuova dipendenza Python. FullCalendar via CDN, non npm.
- **Tenant filter:** ogni query filtra `tenant_id == CURRENT_TENANT`. La costante `CURRENT_TENANT = 1` in cima al router (pattern esistente). Usa `current_tenant_id()` da `app.context` dove serve nei service/handler.
- **Soft-delete:** `is_active=False`, mai DELETE fisico. Le query di lettura filtrano `is_active == True`.
- **Form-based API:** POST/PUT accettano `Form(...)`, non JSON. Il frontend usa `FormData`.
- **RBAC:** endpoint protetti con `Depends(requires_permission("view_calendar"|"manage_calendar"))` (pattern `app/services/rbac.py:391`). Nuovi permessi aggiunti a `PERMISSIONS` + preset.
- **i18n da subito:** ogni stringa UI nuova nelle 5 lingue (`it/en/fr/de/es`) in `app/static/js/i18n.js` + `data-i18n`, stesso commit.
- **Cache-buster:** static referenziati con `?v={{ app_version }}`.
- **Nuove tabelle:** create automaticamente al boot da `create_tables()` → `Base.metadata.create_all()` (`app/database.py:35`), purché il modello sia importato in `app/models`. Fornire comunque uno script di migrazione esplicito idempotente + voce `strumenti`.
- **SQLAlchemy 2.0:** `Mapped[type]` + `mapped_column`. Enum utente-facing via `python Enum` (come `ActivityType`).
- **Datetime:** ISO 8601 in input/output. Parsing con `datetime.fromisoformat` (gestisci suffisso `Z` → sostituisci con `+00:00`). Default temporali via `now_utc()` da `app.services.clock`.
- **Versioning:** a fine fase bump `app/main.py` (versione attuale `3.5.0-alpha.172.239` → `.240`) + `CHANGELOG.md` + `docs/STATO.md`, commit stesso giro. Commit via `git commit -F <file>` (heredoc bloccato da hook; costruisci il file con bash `printf`, non PowerShell, per evitare BOM).
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...` (il `python` nudo su questa macchina è lo stub Microsoft Store; `py` non ha pytest).

---

### Task 1: Modello CalendarEvent + migrazione

Nuova tabella `calendar_events`. Include già le colonne sync (usate in Fase C) per non ri-migrare.

**Files:**
- Modify: `app/models/models.py` (aggiungi enum `CalendarEventStatus` + classe `CalendarEvent` in fondo, vicino agli altri modelli; verifica che `JSON`, `Boolean`, `ForeignKey`, `Enum`, `Text`, `String`, `Integer`, `DateTime` siano già importati — lo sono).
- Create: `scripts/migrate_calendar_events.py`
- Modify: `strumenti.bat` e `strumenti.sh` (voce menu, pattern voce `migrate_oauth_calendar.py`)
- Test: `tests/test_calendar_event_model.py`

**Interfaces:**
- Produces: modello `CalendarEvent` (tabella `calendar_events`) con i campi elencati sotto; enum `CalendarEventStatus` (`confirmed`/`tentative`/`cancelled`). Script `scripts/migrate_calendar_events.py::main()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_event_model.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from app.models.models import Base, CalendarEvent, CalendarEventStatus


def _engine():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return e


def test_calendar_events_table_columns():
    cols = {c["name"] for c in inspect(_engine()).get_columns("calendar_events")}
    expected = {
        "id", "tenant_id", "title", "description", "start_at", "end_at", "all_day",
        "location", "meeting_url", "status", "owner_user_id",
        "acquisition_id", "project_id", "activity_id", "client_id",
        "attendees", "source", "external_calendar_id", "external_event_id",
        "sync_state", "last_synced_at", "sync_error",
        "is_active", "created_by", "created_at", "updated_at",
    }
    assert expected <= cols


def test_status_enum_values():
    assert {s.value for s in CalendarEventStatus} == {"confirmed", "tentative", "cancelled"}


def test_defaults():
    ev = CalendarEvent(title="X")
    assert CalendarEvent.__table__.c.all_day.default.arg is False
    assert CalendarEvent.__table__.c.is_active.default.arg is True
    assert CalendarEvent.__table__.c.source.default.arg == "claqo"
    assert CalendarEvent.__table__.c.sync_state.default.arg == "local"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_event_model.py -v`
Expected: FAIL (ImportError: cannot import name `CalendarEvent`).

- [ ] **Step 3: Add the enum + model**

In `app/models/models.py`, vicino agli altri enum (es. dopo `ActivityDirection`), aggiungi:

```python
class CalendarEventStatus(str, enum.Enum):
    confirmed = "confirmed"
    tentative = "tentative"
    cancelled = "cancelled"
```

E in fondo alla sezione modelli (es. dopo la classe `Activity`), aggiungi:

```python
class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer, default=1, index=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    meeting_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    status: Mapped[CalendarEventStatus] = mapped_column(
        Enum(CalendarEventStatus), default=CalendarEventStatus.confirmed)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    # Link espliciti nullable (pattern codebase: integrità FK + tenant filter)
    acquisition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("acquisitions.id"), nullable=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    activity_id: Mapped[Optional[int]] = mapped_column(ForeignKey("activities.id"), nullable=True, index=True)
    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True, index=True)
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    # Sync (usati in Fase C) — introdotti ora per non ri-migrare
    source: Mapped[str] = mapped_column(String(20), default="claqo", nullable=False)  # claqo|google
    external_calendar_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_event_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    sync_state: Mapped[str] = mapped_column(String(20), default="local", nullable=False)  # local|synced|pending_push|error
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_utc, onupdate=now_utc)
```

(Verifica in cima a `models.py` che `enum` sia importato — lo è, usato da `ActivityType`. `JSON` è importato da sqlalchemy — verifica; se manca, aggiungi `JSON` all'import `from sqlalchemy import (...)`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_event_model.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Write the migration script**

```python
# scripts/migrate_calendar_events.py
"""Migrazione non distruttiva — Fase B calendario.

Crea la tabella calendar_events. Idempotente (create_all salta l'esistente).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine
from app.models.models import Base, CalendarEvent  # noqa: F401


def main():
    Base.metadata.create_all(engine, tables=[CalendarEvent.__table__])
    print("OK: tabella calendar_events creata/verificata.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Add strumenti menu entry**

In `strumenti.bat` e `strumenti.sh`, aggiungi una voce che esegue `python scripts/migrate_calendar_events.py` (etichetta "Migra calendario (Fase B)"), copiando lo stile della voce `migrate_oauth_calendar.py` in ciascun file.

- [ ] **Step 7: Verify idempotency + boot auto-create**

Run: `.venv/Scripts/python.exe scripts/migrate_calendar_events.py && .venv/Scripts/python.exe scripts/migrate_calendar_events.py`
Expected: entrambe stampano `OK:` senza errori.

- [ ] **Step 8: Commit**

```bash
git add app/models/models.py scripts/migrate_calendar_events.py strumenti.bat strumenti.sh tests/test_calendar_event_model.py
git commit -F <msgfile>
# "feat(calendar): modello CalendarEvent + tabella calendar_events + migrazione"
```

---

### Task 2: Permessi RBAC view_calendar / manage_calendar

**Files:**
- Modify: `app/services/rbac.py` (dict `PERMISSIONS` ~riga 38-125 + `PRESET_PERMISSIONS` ~riga 137-200)
- Test: `tests/test_calendar_permissions.py`

**Interfaces:**
- Produces: chiavi permesso `view_calendar` e `manage_calendar` in `ALL_PERMISSION_KEYS`, assegnate ai preset `manager`, `producer`, `accounting` (e `admin` le ha via `list(ALL_PERMISSION_KEYS)`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_permissions.py
from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


def test_calendar_permissions_exist():
    assert "view_calendar" in ALL_PERMISSION_KEYS
    assert "manage_calendar" in ALL_PERMISSION_KEYS


def test_calendar_permissions_in_presets():
    for role in ("manager", "producer", "accounting"):
        assert "view_calendar" in PRESET_PERMISSIONS[role], role
    for role in ("manager", "producer"):
        assert "manage_calendar" in PRESET_PERMISSIONS[role], role


def test_admin_has_calendar_via_all():
    assert "view_calendar" in PRESET_PERMISSIONS["admin"]
    assert "manage_calendar" in PRESET_PERMISSIONS["admin"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_permissions.py -v`
Expected: FAIL (chiavi assenti).

- [ ] **Step 3: Add the permission category + preset entries**

In `app/services/rbac.py`, dentro `PERMISSIONS`, aggiungi una nuova categoria dopo `"Acquisizioni"`:

```python
    "Calendario": {
        "view_calendar":   ["Visualizza calendario e appuntamenti"],
        "manage_calendar": ["Crea/modifica/elimina appuntamenti"],
    },
```

In `PRESET_PERMISSIONS`, aggiungi:
- alla lista `"manager"`: `"view_calendar", "manage_calendar",`
- alla lista `"producer"`: `"view_calendar", "manage_calendar",`
- alla lista `"accounting"`: `"view_calendar",`

(`admin` = `list(ALL_PERMISSION_KEYS)`, prende automaticamente le nuove.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_permissions.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/rbac.py tests/test_calendar_permissions.py
git commit -F <msgfile>
# "feat(calendar): permessi RBAC view_calendar/manage_calendar"
```

---

### Task 3: Router calendar — CRUD API + list con marcatori

Endpoint CRUD Form-based + list con range temporale e marcatori derivati.

**Files:**
- Create: `app/routers/calendar.py`
- Modify: `app/main.py` (import ~riga 34, `include_router` ~riga 2838)
- Test: `tests/test_calendar_api.py`

**Interfaces:**
- Consumes: `CalendarEvent`, `CalendarEventStatus` (Task 1); permessi (Task 2).
- Produces:
  - `GET /calendar/api/events?start&end&owner&scope=mine|team&acquisition_id&project_id` → `{"events": [...], "markers": [...]}`. Ogni event serializzato con `_serialize_event(ev)`.
  - `POST /calendar/api/events` (Form: `title`, `start_at`, `end_at`, `all_day?`, `location?`, `meeting_url?`, `status?`, `acquisition_id?`, `project_id?`, `activity_id?`, `client_id?`) → `{"id": ..., ...}`.
  - `PUT /calendar/api/events/{id}` (stessi Form opzionali) → evento aggiornato.
  - `DELETE /calendar/api/events/{id}` → `{"ok": True}` (soft-delete).
  - Helper `_parse_dt(s: str) -> datetime`, `_serialize_event(ev) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_api.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Acquisition
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
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="manager", name="Mgr",
                permissions=["view_calendar", "manage_calendar", "view_acquisitions", "manage_acquisitions"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Lucky")); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_create_list_update_delete_event(client):
    c, s = client
    r = c.post("/calendar/api/events", data={
        "title": "Call cliente", "start_at": "2026-07-10T10:00:00",
        "end_at": "2026-07-10T11:00:00", "client_id": "1"})
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    lst = c.get("/calendar/api/events", params={"start": "2026-07-01", "end": "2026-07-31"}).json()
    assert any(ev["id"] == eid for ev in lst["events"])
    ev = next(ev for ev in lst["events"] if ev["id"] == eid)
    assert ev["title"] == "Call cliente"
    assert ev["client_id"] == 1
    r2 = c.put(f"/calendar/api/events/{eid}", data={"title": "Call rinviata"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["title"] == "Call rinviata"
    assert c.delete(f"/calendar/api/events/{eid}").status_code == 200
    lst2 = c.get("/calendar/api/events", params={"start": "2026-07-01", "end": "2026-07-31"}).json()
    assert all(ev["id"] != eid for ev in lst2["events"])


def test_list_range_excludes_outside(client):
    c, _ = client
    c.post("/calendar/api/events", data={"title": "Luglio", "start_at": "2026-07-15T09:00:00",
           "end_at": "2026-07-15T10:00:00"})
    out = c.get("/calendar/api/events", params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    assert all(ev["title"] != "Luglio" for ev in out["events"])


def test_markers_from_acquisition_close_date(client):
    c, s = client
    s.add(Acquisition(id=1, tenant_id=1, title="Deal", stage="lead",
                      expected_close_date="2026-07-20", is_active=True)); s.commit()
    r = c.get("/calendar/api/events", params={"start": "2026-07-01", "end": "2026-07-31"}).json()
    assert any(m.get("kind") == "acquisition_close" for m in r["markers"])


def test_create_requires_manage_permission(client, monkeypatch):
    c, s = client
    from app.models.models import Role
    role = s.query(Role).first()
    role.permissions = ["view_calendar"]  # solo view, no manage
    s.commit()
    r = c.post("/calendar/api/events", data={"title": "X", "start_at": "2026-07-10T10:00:00",
               "end_at": "2026-07-10T11:00:00"})
    assert r.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_api.py -v`
Expected: FAIL (404 — router non esiste ancora).

- [ ] **Step 3: Create the router**

```python
# app/routers/calendar.py
"""Router calendario — Fase B (v3.5.0-alpha.172.240).

CRUD CalendarEvent Form-based + list con range temporale e marcatori
derivati (Activity.next_action_date, Acquisition.expected_close_date).
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import (
    CalendarEvent, CalendarEventStatus, Activity, Acquisition,
)
from app.services.rbac import requires_permission

CURRENT_TENANT = 1
router = APIRouter(tags=["calendar"])

RequireView = Depends(requires_permission("view_calendar"))
RequireManage = Depends(requires_permission("manage_calendar"))


def _parse_dt(s: str) -> datetime:
    if not s:
        raise HTTPException(400, "Data mancante")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, f"Data non valida: {s}")


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def _serialize_event(ev: CalendarEvent) -> dict:
    return {
        "id": ev.id, "title": ev.title, "description": ev.description,
        "start": ev.start_at.isoformat() if ev.start_at else None,
        "end": ev.end_at.isoformat() if ev.end_at else None,
        "all_day": ev.all_day, "location": ev.location, "meeting_url": ev.meeting_url,
        "status": ev.status.value if ev.status else "confirmed",
        "owner_user_id": ev.owner_user_id,
        "acquisition_id": ev.acquisition_id, "project_id": ev.project_id,
        "activity_id": ev.activity_id, "client_id": ev.client_id,
        "attendees": ev.attendees or [], "source": ev.source,
    }


def _int_or_none(v: Optional[str]) -> Optional[int]:
    if v is None or str(v).strip() in ("", "0"):
        return None
    return int(v)


@router.get("/calendar", response_class=HTMLResponse, dependencies=[RequireView])
async def calendar_page(request: Request):
    from app.main import templates
    return templates.TemplateResponse(
        "pages/calendar.html", {"request": request, "active_page": "calendar"})


@router.get("/calendar/api/events", dependencies=[RequireView])
async def list_events(
    start: Optional[str] = None, end: Optional[str] = None,
    owner: Optional[str] = None, scope: str = "team",
    acquisition_id: Optional[int] = None, project_id: Optional[int] = None,
    request: Request = None, db: Session = Depends(get_db),
):
    q = db.query(CalendarEvent).filter(
        CalendarEvent.tenant_id == CURRENT_TENANT,
        CalendarEvent.is_active == True,  # noqa: E712
    )
    if acquisition_id:
        q = q.filter(CalendarEvent.acquisition_id == acquisition_id)
    if project_id:
        q = q.filter(CalendarEvent.project_id == project_id)
    if scope == "mine":
        from app.services.rbac import current_user
        u = current_user(request)
        q = q.filter(CalendarEvent.owner_user_id == u.id)
    elif owner:
        q = q.filter(CalendarEvent.owner_user_id == int(owner))
    start_dt = _parse_dt(start) if start else None
    end_dt = _parse_dt(end) if end else None
    if start_dt:
        q = q.filter(CalendarEvent.end_at >= start_dt)
    if end_dt:
        q = q.filter(CalendarEvent.start_at <= end_dt)
    events = [_serialize_event(ev) for ev in q.all()]

    # Marcatori derivati (read-only): Acquisition.expected_close_date + Activity.next_action_date
    markers = []
    aq = db.query(Acquisition).filter(
        Acquisition.tenant_id == CURRENT_TENANT, Acquisition.is_active == True,  # noqa: E712
        Acquisition.expected_close_date.isnot(None))
    for a in aq.all():
        d = a.expected_close_date
        if start_dt and d < start_dt.date():
            continue
        if end_dt and d > end_dt.date():
            continue
        markers.append({"kind": "acquisition_close", "date": d.isoformat(),
                        "title": a.title, "acquisition_id": a.id})
    acts = db.query(Activity).filter(
        Activity.tenant_id == CURRENT_TENANT, Activity.is_active == True,  # noqa: E712
        Activity.next_action_date.isnot(None))
    for act in acts.all():
        d = act.next_action_date
        if start_dt and d < start_dt.date():
            continue
        if end_dt and d > end_dt.date():
            continue
        markers.append({"kind": "activity_next", "date": d.isoformat(),
                        "title": act.subject, "activity_id": act.id,
                        "acquisition_id": act.acquisition_id})
    return {"events": events, "markers": markers}


def _apply_fields(ev: CalendarEvent, *, title, start_at, end_at, all_day, location,
                  meeting_url, status, acquisition_id, project_id, activity_id, client_id,
                  creating: bool):
    if title is not None:
        ev.title = title.strip()
    if start_at is not None:
        ev.start_at = _parse_dt(start_at)
    if end_at is not None:
        ev.end_at = _parse_dt(end_at)
    if all_day is not None:
        ev.all_day = str(all_day).lower() in ("1", "true", "on", "yes")
    if location is not None:
        ev.location = location.strip() or None
    if meeting_url is not None:
        ev.meeting_url = meeting_url.strip() or None
    if status is not None and status.strip():
        ev.status = CalendarEventStatus(status.strip())
    if acquisition_id is not None:
        ev.acquisition_id = _int_or_none(acquisition_id)
    if project_id is not None:
        ev.project_id = _int_or_none(project_id)
    if activity_id is not None:
        ev.activity_id = _int_or_none(activity_id)
    if client_id is not None:
        ev.client_id = _int_or_none(client_id)


@router.post("/calendar/api/events", dependencies=[RequireManage])
async def create_event(
    request: Request,
    title: str = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    all_day: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    meeting_url: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    acquisition_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    activity_id: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    from app.services.rbac import current_user
    u = current_user(request)
    ev = CalendarEvent(tenant_id=CURRENT_TENANT, title=title.strip(),
                       start_at=_parse_dt(start_at), end_at=_parse_dt(end_at),
                       owner_user_id=u.id, created_by=u.id)
    _apply_fields(ev, title=None, start_at=None, end_at=None, all_day=all_day,
                  location=location, meeting_url=meeting_url, status=status,
                  acquisition_id=acquisition_id, project_id=project_id,
                  activity_id=activity_id, client_id=client_id, creating=True)
    db.add(ev); db.commit(); db.refresh(ev)
    return _serialize_event(ev)


@router.put("/calendar/api/events/{event_id}", dependencies=[RequireManage])
async def update_event(
    event_id: int,
    title: Optional[str] = Form(None),
    start_at: Optional[str] = Form(None),
    end_at: Optional[str] = Form(None),
    all_day: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    meeting_url: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    acquisition_id: Optional[str] = Form(None),
    project_id: Optional[str] = Form(None),
    activity_id: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    ev = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id, CalendarEvent.tenant_id == CURRENT_TENANT,
        CalendarEvent.is_active == True).first()  # noqa: E712
    if not ev:
        raise HTTPException(404, "Appuntamento non trovato")
    _apply_fields(ev, title=title, start_at=start_at, end_at=end_at, all_day=all_day,
                  location=location, meeting_url=meeting_url, status=status,
                  acquisition_id=acquisition_id, project_id=project_id,
                  activity_id=activity_id, client_id=client_id, creating=False)
    db.commit(); db.refresh(ev)
    return _serialize_event(ev)


@router.delete("/calendar/api/events/{event_id}", dependencies=[RequireManage])
async def delete_event(event_id: int, db: Session = Depends(get_db)):
    ev = db.query(CalendarEvent).filter(
        CalendarEvent.id == event_id, CalendarEvent.tenant_id == CURRENT_TENANT,
        CalendarEvent.is_active == True).first()  # noqa: E712
    if not ev:
        raise HTTPException(404, "Appuntamento non trovato")
    ev.is_active = False
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4: Register the router in main.py**

In `app/main.py`, riga ~34 (con gli altri import router): `from app.routers import calendar as calendar_router`.
Riga ~2838 (con gli altri include): `app.include_router(calendar_router.router)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add app/routers/calendar.py app/main.py tests/test_calendar_api.py
git commit -F <msgfile>
# "feat(calendar): router CRUD eventi + list con marcatori derivati"
```

---

### Task 4: Pagina /calendar con FullCalendar + nav + i18n

**Files:**
- Create: `app/templates/pages/calendar.html`
- Create: `app/static/js/calendar_page.js`
- Modify: `app/templates/base.html` (nav item ~riga 82-84, area Operativo/Acquisizioni)
- Modify: `app/static/js/i18n.js` (chiavi `nav.calendar`, `cal.*`)
- Test: `tests/test_calendar_page.py`

**Interfaces:**
- Consumes: `GET /calendar/api/events` (Task 3).
- Produces: pagina `/calendar` con contenitore `#calendar-root`; `calendar_page.js` inizializza FullCalendar e crea/modifica eventi via `POST/PUT/DELETE /calendar/api/events`.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_calendar_page.py
from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_renders(client):
    c, _ = client
    html = c.get("/calendar").text
    assert 'id="calendar-root"' in html
    assert "calendar_page.js" in html
    assert 'data-i18n="nav.calendar"' in html or 'data-i18n="cal.title"' in html


def test_i18n_has_calendar_keys():
    import pathlib
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("nav.calendar", "cal.title", "cal.new", "cal.event.title", "cal.event.save"):
        assert key in src, key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_page.py -v`
Expected: FAIL (pagina/nav/i18n assenti).

- [ ] **Step 3: Add i18n keys**

In `app/static/js/i18n.js`, dentro `window.MF_I18N`:

```javascript
  // ── Calendario (Fase B) ───────────────────────────
  'nav.calendar':      {it: 'Calendario',   en: 'Calendar',     fr: 'Calendrier',   de: 'Kalender',      es: 'Calendario'},
  'cal.title':         {it: 'Calendario',   en: 'Calendar',     fr: 'Calendrier',   de: 'Kalender',      es: 'Calendario'},
  'cal.new':           {it: 'Nuovo appuntamento', en: 'New appointment', fr: 'Nouveau rendez-vous', de: 'Neuer Termin', es: 'Nueva cita'},
  'cal.filter.mine':   {it: 'Solo miei',    en: 'Mine only',    fr: 'Les miens',    de: 'Nur meine',     es: 'Solo mios'},
  'cal.filter.team':   {it: 'Team',         en: 'Team',         fr: 'Equipe',       de: 'Team',          es: 'Equipo'},
  'cal.event.title':   {it: 'Titolo',       en: 'Title',        fr: 'Titre',        de: 'Titel',         es: 'Titulo'},
  'cal.event.start':   {it: 'Inizio',       en: 'Start',        fr: 'Debut',        de: 'Beginn',        es: 'Inicio'},
  'cal.event.end':     {it: 'Fine',         en: 'End',          fr: 'Fin',          de: 'Ende',          es: 'Fin'},
  'cal.event.location':{it: 'Luogo',        en: 'Location',     fr: 'Lieu',         de: 'Ort',           es: 'Lugar'},
  'cal.event.link':    {it: 'Link riunione',en: 'Meeting link', fr: 'Lien reunion', de: 'Meeting-Link',  es: 'Enlace reunion'},
  'cal.event.save':    {it: 'Salva',        en: 'Save',         fr: 'Enregistrer',  de: 'Speichern',     es: 'Guardar'},
  'cal.event.delete':  {it: 'Elimina',      en: 'Delete',       fr: 'Supprimer',    de: 'Loschen',       es: 'Eliminar'},
```

- [ ] **Step 4: Add the nav item**

In `app/templates/base.html`, vicino alla voce `acquisitions` (~riga 82-84), aggiungi:

```html
<a href="/calendar" data-nav-id="calendar" class="nav-item {% if active_page == 'calendar' %}active{% endif %}">
  <span class="nav-icon"><i data-lucide="calendar"></i></span> <span data-i18n="nav.calendar">Calendario</span>
</a>
```

(Se le voci nav sono gated da permesso, replica il pattern di gating usato dalla voce acquisitions; se non lo sono, lasciala semplice come sopra — l'endpoint è già protetto da `view_calendar`.)

- [ ] **Step 5: Create the page template**

```html
{# app/templates/pages/calendar.html #}
{% extends "base.html" %}
{% block title %}Calendario · Claqo{% endblock %}
{% block head %}
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.css">
<style>
  #calendar-root { max-width: 1100px; margin: 0 auto; }
  .cal-toolbar { display:flex; gap:12px; align-items:center; margin-bottom:12px; }
  .cal-marker { border:1px dashed var(--accent, #6272f5); opacity:.7; }
</style>
{% endblock %}
{% block content %}
<div class="page-header">
  <h1 data-i18n="cal.title">Calendario</h1>
</div>
<div class="cal-toolbar">
  <select id="cal-scope" class="input">
    <option value="team" data-i18n="cal.filter.team">Team</option>
    <option value="mine" data-i18n="cal.filter.mine">Solo miei</option>
  </select>
  <button class="btn btn-primary" onclick="calNewEvent()" data-i18n="cal.new">Nuovo appuntamento</button>
</div>
<div id="calendar-root"></div>
{% endblock %}
{% block scripts %}
<script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.js"></script>
<script src="/static/js/calendar_page.js?v={{ app_version }}"></script>
{% endblock %}
```

- [ ] **Step 6: Create calendar_page.js**

```javascript
// app/static/js/calendar_page.js — Fase B FullCalendar wiring
let _cal = null;

function calScope() {
  const s = document.getElementById('cal-scope');
  return s ? s.value : 'team';
}

async function calFetchEvents(info, success, failure) {
  try {
    const url = '/calendar/api/events?start=' + encodeURIComponent(info.startStr) +
                '&end=' + encodeURIComponent(info.endStr) + '&scope=' + calScope();
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const evs = (data.events || []).map(e => ({
      id: e.id, title: e.title, start: e.start, end: e.end, allDay: e.all_day,
      extendedProps: { source: e.source, location: e.location, meeting_url: e.meeting_url,
                       acquisition_id: e.acquisition_id, client_id: e.client_id }
    }));
    (data.markers || []).forEach(m => evs.push({
      title: '• ' + m.title, start: m.date, allDay: true, display: 'background',
      classNames: ['cal-marker'], editable: false, extendedProps: { marker: m.kind }
    }));
    success(evs);
  } catch (e) { failure(e); }
}

async function calSaveEvent(fd, id) {
  const method = id ? 'PUT' : 'POST';
  const url = '/calendar/api/events' + (id ? '/' + id : '');
  const r = await fetch(url, { method, body: fd });
  if (!r.ok) { if (window.toast) toast('Errore salvataggio', 'error'); return null; }
  return r.json();
}

function calNewEvent(prefill) {
  prefill = prefill || {};
  const title = prompt(window.mfT ? mfT('cal.event.title') : 'Titolo');
  if (!title) return;
  const start = prefill.start || new Date().toISOString().slice(0, 16);
  const end = prefill.end || start;
  const fd = new FormData();
  fd.append('title', title);
  fd.append('start_at', start);
  fd.append('end_at', end);
  if (prefill.acquisition_id) fd.append('acquisition_id', prefill.acquisition_id);
  if (prefill.client_id) fd.append('client_id', prefill.client_id);
  calSaveEvent(fd, null).then(() => _cal && _cal.refetchEvents());
}

document.addEventListener('DOMContentLoaded', function () {
  const root = document.getElementById('calendar-root');
  if (!root || typeof FullCalendar === 'undefined') return;
  const lang = (window.MF_CURRENT_LANG || localStorage.getItem('mf_lang') || 'it');
  _cal = new FullCalendar.Calendar(root, {
    initialView: 'dayGridMonth',
    locale: lang,
    headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay,listWeek' },
    editable: true,
    events: calFetchEvents,
    dateClick: function (info) { calNewEvent({ start: info.dateStr + 'T09:00', end: info.dateStr + 'T10:00' }); },
    eventDrop: function (info) {
      if (info.event.extendedProps.marker) { info.revert(); return; }
      const fd = new FormData();
      fd.append('start_at', info.event.start.toISOString());
      if (info.event.end) fd.append('end_at', info.event.end.toISOString());
      calSaveEvent(fd, info.event.id);
    },
  });
  _cal.render();
  const sc = document.getElementById('cal-scope');
  if (sc) sc.addEventListener('change', () => _cal.refetchEvents());
});
```

(Riusa `toast`/`mfT` globali; non ridefinirli. Se `MF_CURRENT_LANG` non esiste, il fallback a `localStorage.mf_lang`/`'it'` è sufficiente.)

- [ ] **Step 7: Restart server + run smoke test**

Nota: template Jinja su OneDrive non si ricaricano a runtime — il test pytest avvia un'app fresca, quindi va bene senza riavvio manuale. Ma per lo smoke browser manuale riavvia il server.

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_page.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: JS syntax + grep guard**

Run: `node --check app/static/js/calendar_page.js`
Expected: nessun errore.
Run: `grep -n "calNewEvent\|calFetchEvents\|calSaveEvent" app/static/js/calendar_page.js app/templates/pages/calendar.html`
Expected: funzioni definite in `calendar_page.js` e referenziate.

- [ ] **Step 9: Commit**

```bash
git add app/templates/pages/calendar.html app/static/js/calendar_page.js app/templates/base.html app/static/js/i18n.js tests/test_calendar_page.py
git commit -F <msgfile>
# "feat(calendar): pagina /calendar FullCalendar + nav + i18n 5 lingue"
```

---

### Task 5: Embed Appuntamenti in acquisitions

Nuovo tab "Appuntamenti" nel detail-panel acquisitions che lista i `CalendarEvent` collegati + crea nuovo appuntamento precompilato.

**Files:**
- Modify: `app/templates/pages/acquisitions.html` (tab button ~riga 253-257, content container ~riga 259+, JS `acqDetTab`/load ~riga 803+)
- Modify: `app/static/js/i18n.js` (chiave `acq.detail.tab.calendar`)
- Test: `tests/test_acquisitions_calendar_tab.py`

**Interfaces:**
- Consumes: `GET /calendar/api/events?acquisition_id=` (Task 3); `calNewEvent` non disponibile qui (pagina diversa) → usa una fetch locale.
- Produces: tab `data-tab="calendar"` + container `#det-tab-calendar` con `#det-calendar-list`; funzione `acqDetLoadCalendarEvents(aid)`.

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_acquisitions_calendar_tab.py
from tests.test_calendar_api import client  # noqa: F401


def test_acquisitions_page_has_calendar_tab(client):
    c, _ = client
    html = c.get("/acquisitions").text
    assert 'data-tab="calendar"' in html
    assert 'id="det-tab-calendar"' in html
    assert 'acq.detail.tab.calendar' in html


def test_events_filtered_by_acquisition(client):
    c, s = client
    from app.models.models import Acquisition
    s.add(Acquisition(id=5, tenant_id=1, title="Deal5", stage="lead", is_active=True)); s.commit()
    c.post("/calendar/api/events", data={"title": "Riunione deal5",
           "start_at": "2026-07-12T09:00:00", "end_at": "2026-07-12T10:00:00", "acquisition_id": "5"})
    c.post("/calendar/api/events", data={"title": "Altro",
           "start_at": "2026-07-12T11:00:00", "end_at": "2026-07-12T12:00:00"})
    r = c.get("/calendar/api/events", params={"acquisition_id": 5}).json()
    titles = [e["title"] for e in r["events"]]
    assert "Riunione deal5" in titles and "Altro" not in titles
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_calendar_tab.py -v`
Expected: FAIL (tab assente).

- [ ] **Step 3: Add the i18n key**

In `app/static/js/i18n.js`:

```javascript
  'acq.detail.tab.calendar': {it: 'Appuntamenti', en: 'Appointments', fr: 'Rendez-vous', de: 'Termine', es: 'Citas'},
```

- [ ] **Step 4: Add tab button + content container**

In `app/templates/pages/acquisitions.html`, dentro `.acq-det-tabs` (dopo il bottone `quotes`, ~riga 256):

```html
  <button class="acq-det-tab" data-tab="calendar" onclick="acqDetTab(this,'calendar')" data-i18n="acq.detail.tab.calendar">Appuntamenti</button>
```

Dopo il container `#det-tab-quotes` (~riga 334), aggiungi:

```html
{# Calendar tab (Fase B) #}
<div class="acq-det-content" id="det-tab-calendar">
  <div id="det-calendar-list"></div>
  <button class="btn btn-sm" onclick="acqNewAppointment()" data-i18n="cal.new">Nuovo appuntamento</button>
</div>
```

- [ ] **Step 5: Add the JS load + create functions**

In `app/templates/pages/acquisitions.html`, vicino a `acqDetLoadActivities` (~riga 810), aggiungi:

```javascript
async function acqDetLoadCalendarEvents(aid) {
  try {
    const r = await api('GET', '/calendar/api/events?acquisition_id=' + aid);
    const list = document.getElementById('det-calendar-list');
    const items = (r && r.events) || [];
    if (!items.length) {
      list.innerHTML = '<div class="text-muted" data-i18n="acq.detail.noAppointments">Nessun appuntamento.</div>';
      if (window.applyI18n) applyI18n(list);
      return;
    }
    list.innerHTML = '';
    items.forEach(ev => {
      const el = document.createElement('div');
      el.className = 'acq-activity-item';
      const when = ev.start ? new Date(ev.start).toLocaleString() : '';
      el.innerHTML = '<b>' + escapeHtml(ev.title) + '</b><br><span class="text-muted">' + escapeHtml(when) + '</span>';
      list.appendChild(el);
    });
  } catch (e) {}
}

async function acqNewAppointment() {
  const aid = window._acqCurrentId;
  if (!aid) return;
  const title = prompt(window.mfT ? mfT('cal.event.title') : 'Titolo');
  if (!title) return;
  const start = new Date().toISOString().slice(0, 16);
  const fd = new FormData();
  fd.append('title', title);
  fd.append('start_at', start);
  fd.append('end_at', start);
  fd.append('acquisition_id', aid);
  const r = await fetch('/calendar/api/events', { method: 'POST', body: fd });
  if (r.ok) acqDetLoadCalendarEvents(aid);
  else if (window.toast) toast('Errore', 'error');
}
```

Nel punto in cui il detail-panel viene aperto/caricato (dove viene impostato l'id corrente e caricate le activities — cerca dove `acqDetLoadActivities` viene chiamato e dove si memorizza l'id trattativa), assicurati che l'id sia disponibile come `window._acqCurrentId = aid;` e che, all'attivazione del tab calendar, si chiami `acqDetLoadCalendarEvents(aid)`. Estendi `acqDetTab` così:

```javascript
function acqDetTab(btn, tab) {
  document.querySelectorAll('.acq-det-tab').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.acq-det-content').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('det-tab-' + tab).classList.add('active');
  if (tab === 'calendar' && window._acqCurrentId) acqDetLoadCalendarEvents(window._acqCurrentId);
}
```

(Verifica il nome reale della variabile che tiene l'id della trattativa aperta leggendo la funzione che apre il detail; se esiste già un `currentAcqId`/simile, riusalo invece di `window._acqCurrentId` e adegua le due funzioni. Non introdurre una seconda fonte di verità.)

- [ ] **Step 6: Add the i18n key for the empty state**

In `app/static/js/i18n.js`:

```javascript
  'acq.detail.noAppointments': {it: 'Nessun appuntamento.', en: 'No appointments.', fr: 'Aucun rendez-vous.', de: 'Keine Termine.', es: 'Sin citas.'},
```

- [ ] **Step 7: Restart + run smoke test + grep guard**

Run: `.venv/Scripts/python.exe -m pytest tests/test_acquisitions_calendar_tab.py -v`
Expected: PASS (2 passed).
Run: `grep -n "acqDetLoadCalendarEvents\|acqNewAppointment" app/templates/pages/acquisitions.html`
Expected: definite e referenziate; `escapeHtml`/`applyI18n`/`api`/`mfT` NON ridefinite.

- [ ] **Step 8: Commit**

```bash
git add app/templates/pages/acquisitions.html app/static/js/i18n.js tests/test_acquisitions_calendar_tab.py
git commit -F <msgfile>
# "feat(calendar): tab Appuntamenti in acquisitions (i18n)"
```

---

### Task 6: Capability AI propose_calendar_event + chiusura fase

**Files:**
- Modify: `app/services/ai_tools.py` (aggiungi entry al TOOLS array, ~riga 1282)
- Modify: `app/services/ai_assistant.py` (aggiungi handler `@ai_capability` ~riga 4495)
- Modify: `app/main.py` (bump versione `.239` → `.240`), `CHANGELOG.md`, `docs/STATO.md`
- Test: `tests/test_calendar_capability.py`

**Interfaces:**
- Consumes: `CalendarEvent`, `_parse_dt` logic (replicata nel handler); `ai_capability` decorator, `current_tenant_id`.
- Produces: capability `propose_calendar_event` (params: `title`, `start_at`, `end_at`, `acquisition_id?`, `project_id?`, `client_id?`, `location?`, `meeting_url?`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_capability.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, CalendarEvent
from app.services.ai_assistant import _ACTION_HANDLERS


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.commit()
    return s


def test_capability_registered():
    assert "propose_calendar_event" in _ACTION_HANDLERS


def test_apply_creates_event():
    s = _session()
    fn = _ACTION_HANDLERS["propose_calendar_event"][0] if isinstance(
        _ACTION_HANDLERS["propose_calendar_event"], tuple) else _ACTION_HANDLERS["propose_calendar_event"]
    res = fn(s, {"title": "Kickoff", "start_at": "2026-07-15T10:00:00",
                 "end_at": "2026-07-15T11:00:00", "client_id": 1})
    s.commit()
    assert res["created"] is True
    ev = s.query(CalendarEvent).filter_by(id=res["calendar_event_id"]).first()
    assert ev.title == "Kickoff" and ev.client_id == 1
```

(Nota: `_ACTION_HANDLERS[name]` può essere la funzione o una tupla `(fn, category)` a seconda di come `_registry_get_handlers()` la espone. Il test gestisce entrambi; l'implementatore verifichi la forma reale leggendo `_registry_get_handlers` e semplifichi il test di conseguenza.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_capability.py -v`
Expected: FAIL (capability non registrata).

- [ ] **Step 3: Add the tool schema**

In `app/services/ai_tools.py`, nel TOOLS array (vicino a `propose_activity`), aggiungi:

```python
    {
        "name": "propose_calendar_event",
        "category": "mutation",
        "description": ("Propone un appuntamento in calendario (riunione/call). "
                        "start_at/end_at in ISO 8601. Collega opzionalmente a una "
                        "trattativa (acquisition_id), progetto (project_id) o cliente (client_id)."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start_at": {"type": "string", "description": "ISO 8601, es. 2026-07-15T10:00:00"},
                "end_at": {"type": "string", "description": "ISO 8601"},
                "acquisition_id": {"type": "integer"},
                "project_id": {"type": "integer"},
                "client_id": {"type": "integer"},
                "location": {"type": "string"},
                "meeting_url": {"type": "string"},
            },
            "required": ["title", "start_at", "end_at"],
        },
        "handler": "propose_calendar_event",
    },
```

- [ ] **Step 4: Add the handler**

In `app/services/ai_assistant.py`, vicino a `_h_propose_activity` (~riga 4495), aggiungi:

```python
@ai_capability("propose_calendar_event")
def _h_propose_calendar_event(db: Session, data: dict) -> dict:
    from datetime import datetime
    from app.models.models import CalendarEvent
    title = (data.get("title") or "").strip()
    if not title:
        raise ValueError("Manca 'title'")

    def _dt(s):
        if not s:
            raise ValueError("Manca start_at/end_at")
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))

    ev = CalendarEvent(
        tenant_id=current_tenant_id(), title=title,
        start_at=_dt(data.get("start_at")), end_at=_dt(data.get("end_at")),
        acquisition_id=data.get("acquisition_id"), project_id=data.get("project_id"),
        client_id=data.get("client_id"),
        location=(data.get("location") or None), meeting_url=(data.get("meeting_url") or None))
    db.add(ev); db.flush()
    return {"created": True, "calendar_event_id": ev.id,
            "message": f"Appuntamento '{title}' proposto."}
```

(Verifica che `current_tenant_id` e `Session` siano già importati nel file — lo sono, usati dagli altri handler. `CalendarEvent` importato localmente per sicurezza.)

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_capability.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Bump version + CHANGELOG + STATO**

- `app/main.py`: `version="3.5.0-alpha.172.239"` → `"3.5.0-alpha.172.240"`.
- `CHANGELOG.md`: nuova voce `v3.5.0-alpha.172.240` — Fase B: entità CalendarEvent + tabella calendar_events, pagina `/calendar` FullCalendar (mese/settimana/giorno/agenda), CRUD eventi Form-based con permessi view_calendar/manage_calendar, marcatori derivati (scadenze trattative + next action), tab Appuntamenti in acquisitions, capability AI propose_calendar_event, i18n 5 lingue.
- `docs/STATO.md`: versione → `.240`; completato → Fase B calendario; prossimo step → Fase C (sync Google bidirezionale: `google_calendar.py`, push su calendario "Claqo", overlay primario, che accende il toggle auto_sync_calendar già presente).

- [ ] **Step 7: Run full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (≥1033 + i nuovi test). Se un test preesistente rompe per il nuovo router/nav, correggilo minimamente e annotalo.

- [ ] **Step 8: Commit**

```bash
git add app/services/ai_tools.py app/services/ai_assistant.py app/main.py CHANGELOG.md docs/STATO.md tests/test_calendar_capability.py
git commit -F <msgfile>
# "feat(calendar): capability AI propose_calendar_event + Fase B v3.5.0-alpha.172.240"
```

---

## Self-Review

**1. Spec coverage (sezione Fase B della spec):**
- Entità `CalendarEvent` generica con link espliciti nullable → Task 1 ✓
- Colonne sync per Fase C incluse ora → Task 1 ✓
- Router CRUD `/calendar/api/events` + list con range → Task 3 ✓
- Permessi `view_calendar`/`manage_calendar` + seed preset → Task 2 ✓
- Marcatori derivati (`Activity.next_action_date`, `Acquisition.expected_close_date`) → Task 3 ✓
- Pagina FullCalendar mese/settimana/giorno/agenda, click-crea, drag→PUT → Task 4 ✓
- Filtro owner (mine/team) → Task 3 (param) + Task 4 (select) ✓
- Embed acquisitions tab Appuntamenti → Task 5 ✓
- Capability AI `propose_calendar_event` → Task 6 ✓
- i18n 5 lingue, cache-buster, migrazione + strumenti, versioning → Task 1/4/6 ✓

**2. Placeholder scan:** nessun TODO/TBD; ogni step di codice mostra il codice.

**3. Type consistency:** `_serialize_event`, `_parse_dt`, `_apply_fields`, `CalendarEvent`, `CalendarEventStatus`, `acqDetLoadCalendarEvents`, `calNewEvent`/`calFetchEvents`/`calSaveEvent`, `propose_calendar_event` / `calendar_event_id` coerenti tra i task e i test.

## Note

- **Marcatori vs eventi:** i marcatori derivati sono read-only (background in FullCalendar, `editable:false`); l'`eventDrop` li ignora (`info.revert()` se `extendedProps.marker`).
- **Timezone:** Fase B tratta i datetime come forniti (ISO, naive/UTC coerente con `now_utc()` del resto del progetto). La normalizzazione fine tz è fuori scope Fase B.
- **YAGNI:** niente ricorrenze, niente notifiche/reminder, niente inviti email in Fase B. Le colonne sync esistono ma non sono usate finché Fase C.

## Execution Handoff

Fase C (sync Google) e D (documenti) avranno il proprio piano dopo Fase B.
