# Calendario Fase C — Sync Google bidirezionale — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sincronizzare per-utente gli appuntamenti Claqo verso un calendario secondario "Claqo" su Google (push) e mostrare gli eventi Google esistenti in overlay read-only, con autosync se il toggle è ON più un bottone "Sincronizza".

**Architecture:** `google_calendar.py` isola le chiamate HTTP (urllib, unico helper `_google_request` mockabile). `calendar_sync.py` orchestra (autosync on-save + push/delete pending in blocco). Il router calendario aggancia l'autosync nei CRUD, espone `POST /calendar/api/sync` e `GET /calendar/api/google-overlay`, e serializza lo stato sync. Il frontend aggiunge overlay Google read-only, bottone Sincronizza, checkbox "Mostra Google" e badge synced.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, SQLite, urllib.request (coerente con `oauth_providers`), FullCalendar 6, vanilla JS, i18n client-side.

## Global Constraints

- **Nessuna migrazione DB.** Colonne sync già su `CalendarEvent` (`source`, `external_calendar_id`, `external_event_id`, `sync_state`, `last_synced_at`, `sync_error`); `UserOAuthToken.auto_sync_calendar` + `claqo_calendar_id` già presenti (Fase A/B).
- **Nessuna nuova dipendenza Python.** HTTP via `urllib.request` come `oauth_providers.py`. Un solo helper `_google_request` → punto di mock nei test (monkeypatch).
- **Token:** `get_valid_access_token(db, user_id, "google") -> Optional[str]` (auto-refresh, NON committa). `get_token(db, user_id, "google") -> Optional[UserOAuthToken]`. Entrambi da `app.services.oauth_providers`.
- **Scope disponibili:** `calendar.app.created` (solo calendario "Claqo" + suoi eventi), `calendar.readonly` (overlay altri calendari). Push SOLO sul calendario Claqo; overlay ESCLUDE il calendario Claqo.
- **Per-utente:** sync sugli eventi `owner_user_id == user`; autosync usa `ev.owner_user_id` (proprietario dell'evento = titolare del Google).
- **Best-effort:** nessuna chiamata Google blocca il CRUD locale o il render. Overlay/errore → lista vuota, mai 500.
- **Form-based** per scrittura, **i18n 5 lingue**, **cache-buster** su static. `mfT(key)` 1-arg (chiavi sempre definite). Helper globali non ridefiniti.
- **Interprete test:** `.venv/Scripts/python.exe -m pytest ...`. Commit via `git commit -F <file>` (`printf` bash per il messaggio, no BOM).
- **Versione:** `3.5.0-alpha.172.241` → `.242` (Task 5).

---

### Task 1: `google_calendar.py` — client Google Calendar API

**Files:**
- Create: `app/services/google_calendar.py`
- Test: `tests/test_google_calendar.py`

**Interfaces:**
- Consumes: `get_valid_access_token`, `get_token` (oauth_providers); `now_utc` (clock); `CalendarEvent`.
- Produces:
  - `_google_request(method, url, token, body=None, params=None) -> dict` (helper HTTP, mock point).
  - `ensure_claqo_calendar(db, user_id) -> Optional[str]`
  - `push_event(db, user_id, ev) -> bool`
  - `delete_event(db, user_id, ev) -> bool`
  - `list_google_events(db, user_id, time_min, time_max) -> list[dict]`
  - `_event_to_google(ev) -> dict`, `_normalize_google_event(g, cal_summary) -> dict`
  - Costante `CLAQO_CALENDAR_SUMMARY = "Claqo"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_google_calendar.py
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken, CalendarEvent
from app.services.clock import now_utc
from app.services import google_calendar as gc


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


def _connect(s, auto=False, cal_id=None):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1),
                         auto_sync_calendar=auto, claqo_calendar_id=cal_id))
    s.commit()


def _ev(s, **kw):
    base = dict(tenant_id=1, title="X", start_at=datetime(2026, 7, 10, 10, 0),
                end_at=datetime(2026, 7, 10, 11, 0), owner_user_id=1)
    base.update(kw)
    ev = CalendarEvent(**base)
    s.add(ev); s.commit(); s.refresh(ev)
    return ev


def test_ensure_creates_calendar(monkeypatch):
    s = _session(); _connect(s)
    calls = []
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: (calls.append((m, u)), {"id": "cal123"})[1])
    cid = gc.ensure_claqo_calendar(s, 1)
    assert cid == "cal123"
    assert s.query(UserOAuthToken).first().claqo_calendar_id == "cal123"


def test_ensure_reuses_existing(monkeypatch):
    s = _session(); _connect(s, cal_id="existing")
    monkeypatch.setattr(gc, "_google_request",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("non deve chiamare")))
    assert gc.ensure_claqo_calendar(s, 1) == "existing"


def test_ensure_none_if_not_connected():
    s = _session()
    assert gc.ensure_claqo_calendar(s, 1) is None


def test_push_insert_sets_external_id(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    ev = _ev(s)
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: {"id": "evt1"} if m == "POST" else {})
    assert gc.push_event(s, 1, ev) is True
    assert ev.external_event_id == "evt1"
    assert ev.sync_state == "synced"
    assert ev.last_synced_at is not None


def test_push_update_when_external_id(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    ev = _ev(s, external_event_id="evtX", external_calendar_id="cal1")
    seen = {}
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: (seen.setdefault("m", m), {})[1])
    assert gc.push_event(s, 1, ev) is True
    assert seen["m"] == "PUT"
    assert ev.sync_state == "synced"


def test_push_error_sets_error_state(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    ev = _ev(s)
    def boom(*a, **k): raise RuntimeError("500")
    monkeypatch.setattr(gc, "_google_request", boom)
    assert gc.push_event(s, 1, ev) is False
    assert ev.sync_state == "error"
    assert ev.sync_error


def test_delete_noop_without_external_id():
    s = _session(); _connect(s, cal_id="cal1")
    ev = _ev(s)
    assert gc.delete_event(s, 1, ev) is True
    assert ev.sync_state == "deleted"


def test_delete_calls_api(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    ev = _ev(s, external_event_id="evtX", external_calendar_id="cal1")
    seen = {}
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: (seen.setdefault("m", m), {})[1])
    assert gc.delete_event(s, 1, ev) is True
    assert seen["m"] == "DELETE"
    assert ev.external_event_id is None
    assert ev.sync_state == "deleted"


def test_list_overlay_excludes_claqo(monkeypatch):
    s = _session(); _connect(s, cal_id="claqoCal")

    def fake(m, url, t, body=None, params=None):
        if url.endswith("/users/me/calendarList"):
            return {"items": [{"id": "claqoCal", "summary": "Claqo"},
                              {"id": "primary", "summary": "Personale"}]}
        if "/calendars/primary/events" in url:
            return {"items": [{"id": "g1", "summary": "Riunione",
                               "start": {"dateTime": "2026-07-10T09:00:00Z"},
                               "end": {"dateTime": "2026-07-10T10:00:00Z"}}]}
        return {"items": []}

    monkeypatch.setattr(gc, "_google_request", fake)
    out = gc.list_google_events(s, 1, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z")
    assert len(out) == 1
    assert out[0]["title"] == "Riunione"
    assert out[0]["read_only"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.google_calendar`).

- [ ] **Step 3: Create `google_calendar.py`**

```python
# app/services/google_calendar.py
"""Google Calendar API client — Fase C (v3.5.0-alpha.172.242).

Layer HTTP isolato (urllib, coerente con oauth_providers). Tutte le chiamate
passano da `_google_request` → punto unico di mock nei test.

Scope (Fase A): calendar.app.created (crea/gestisce il calendario secondario
'Claqo' e i suoi eventi), calendar.readonly (overlay degli altri calendari).
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from sqlalchemy.orm import Session

from app.services.clock import now_utc
from app.services.oauth_providers import get_token, get_valid_access_token

log = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/calendar/v3"
CLAQO_CALENDAR_SUMMARY = "Claqo"


def _google_request(method: str, url: str, token: str, body=None, params=None) -> dict:
    """Chiamata HTTP all'API Google Calendar. Ritorna dict JSON (o {} se vuoto).
    Punto unico di mock nei test. Solleva urllib.error.HTTPError su status >=400
    (i chiamanti gestiscono i casi rilevanti, es. 404 su delete)."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw else {}


def ensure_claqo_calendar(db: Session, user_id: int) -> Optional[str]:
    row = get_token(db, user_id, "google")
    if not row:
        return None
    if row.claqo_calendar_id:
        return row.claqo_calendar_id
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return None
    res = _google_request("POST", _API_BASE + "/calendars", token,
                          body={"summary": CLAQO_CALENDAR_SUMMARY})
    cal_id = (res or {}).get("id")
    if cal_id:
        row.claqo_calendar_id = cal_id
        row.updated_at = now_utc()
    return cal_id


def _event_to_google(ev) -> dict:
    status = "cancelled" if (ev.status and getattr(ev.status, "value", ev.status) == "cancelled") else "confirmed"
    body = {
        "summary": ev.title or "",
        "description": ev.description or "",
        "location": ev.location or "",
        "status": status,
    }
    if ev.all_day:
        body["start"] = {"date": ev.start_at.date().isoformat()}
        body["end"] = {"date": ev.end_at.date().isoformat()}
    else:
        body["start"] = {"dateTime": ev.start_at.isoformat()}
        body["end"] = {"dateTime": ev.end_at.isoformat()}
    return body


def push_event(db: Session, user_id: int, ev) -> bool:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    cal = ensure_claqo_calendar(db, user_id)
    if not cal:
        return False
    try:
        body = _event_to_google(ev)
        base = _API_BASE + "/calendars/" + urllib.parse.quote(cal) + "/events"
        if ev.external_event_id:
            _google_request("PUT", base + "/" + urllib.parse.quote(ev.external_event_id), token, body=body)
        else:
            res = _google_request("POST", base, token, body=body)
            ev.external_event_id = (res or {}).get("id")
            ev.external_calendar_id = cal
        ev.sync_state = "synced"
        ev.last_synced_at = now_utc()
        ev.sync_error = None
        return True
    except Exception as e:
        log.warning(f"push_event fallito ev={getattr(ev, 'id', '?')}: {e}")
        ev.sync_state = "error"
        ev.sync_error = str(e)[:500]
        return False


def delete_event(db: Session, user_id: int, ev) -> bool:
    if not ev.external_event_id:
        ev.sync_state = "deleted"
        return True
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return False
    cal = ev.external_calendar_id or ensure_claqo_calendar(db, user_id)
    if not cal:
        return False
    try:
        url = (_API_BASE + "/calendars/" + urllib.parse.quote(cal) +
               "/events/" + urllib.parse.quote(ev.external_event_id))
        _google_request("DELETE", url, token)
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = già assente → idempotente
            log.warning(f"delete_event fallito ev={ev.id}: {e}")
            ev.sync_error = str(e)[:500]
            return False
    except Exception as e:
        log.warning(f"delete_event fallito ev={ev.id}: {e}")
        ev.sync_error = str(e)[:500]
        return False
    ev.external_event_id = None
    ev.sync_state = "deleted"
    ev.sync_error = None
    return True


def _normalize_google_event(g: dict, cal_summary: str) -> dict:
    start = g.get("start", {})
    end = g.get("end", {})
    return {
        "id": g.get("id"),
        "title": g.get("summary") or "(senza titolo)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "all_day": "date" in start,
        "calendar": cal_summary,
        "read_only": True,
    }


def list_google_events(db: Session, user_id: int, time_min: str, time_max: str) -> list:
    token = get_valid_access_token(db, user_id, "google")
    if not token:
        return []
    row = get_token(db, user_id, "google")
    claqo_id = row.claqo_calendar_id if row else None
    try:
        cal_list = _google_request("GET", _API_BASE + "/users/me/calendarList", token) or {}
    except Exception as e:
        log.warning(f"calendarList fallita user={user_id}: {e}")
        return []
    out = []
    for cal in cal_list.get("items", []):
        cid = cal.get("id")
        if not cid or cid == claqo_id:
            continue
        try:
            res = _google_request(
                "GET", _API_BASE + "/calendars/" + urllib.parse.quote(cid) + "/events", token,
                params={"timeMin": time_min, "timeMax": time_max,
                        "singleEvents": "true", "maxResults": "250", "orderBy": "startTime"}) or {}
        except Exception as e:
            log.warning(f"events {cid} falliti: {e}")
            continue
        for g in res.get("items", []):
            if g.get("status") == "cancelled":
                continue
            out.append(_normalize_google_event(g, cal.get("summary") or cid))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_google_calendar.py -v`
Expected: PASS (10 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/google_calendar.py tests/test_google_calendar.py
git commit -F <msgfile>
# "feat(calendar): client Google Calendar API (push/delete/overlay) mockabile"
```

---

### Task 2: `calendar_sync.py` — orchestrazione autosync + sync pending

**Files:**
- Create: `app/services/calendar_sync.py`
- Test: `tests/test_calendar_sync.py`

**Interfaces:**
- Consumes: `google_calendar.push_event/delete_event`; `get_token`; `CalendarEvent`.
- Produces:
  - `maybe_autosync_event(db, user_id, ev, deleted=False) -> None`
  - `sync_user_pending(db, user_id) -> dict` con chiavi `pushed`, `deleted`, `failed`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calendar_sync.py
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken, CalendarEvent
from app.services.clock import now_utc
from app.services import calendar_sync, google_calendar as gc


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


def _connect(s, auto=False):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1),
                         auto_sync_calendar=auto, claqo_calendar_id="cal1"))
    s.commit()


def _ev(s, **kw):
    base = dict(tenant_id=1, title="X", start_at=datetime(2026, 7, 10, 10, 0),
                end_at=datetime(2026, 7, 10, 11, 0), owner_user_id=1)
    base.update(kw)
    ev = CalendarEvent(**base); s.add(ev); s.commit(); s.refresh(ev)
    return ev


def test_autosync_noop_when_toggle_off(monkeypatch):
    s = _session(); _connect(s, auto=False)
    ev = _ev(s)
    monkeypatch.setattr(gc, "_google_request",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("non deve chiamare")))
    calendar_sync.maybe_autosync_event(s, 1, ev)
    assert ev.sync_state == "local"


def test_autosync_pushes_when_on(monkeypatch):
    s = _session(); _connect(s, auto=True)
    ev = _ev(s)
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: {"id": "evt1"} if m == "POST" else {})
    calendar_sync.maybe_autosync_event(s, 1, ev)
    assert ev.sync_state == "synced"
    assert ev.external_event_id == "evt1"


def test_autosync_pending_on_error(monkeypatch):
    s = _session(); _connect(s, auto=True)
    ev = _ev(s)
    def boom(*a, **k): raise RuntimeError("500")
    monkeypatch.setattr(gc, "_google_request", boom)
    calendar_sync.maybe_autosync_event(s, 1, ev)
    assert ev.sync_state == "pending_push"


def test_sync_pending_counts(monkeypatch):
    s = _session(); _connect(s, auto=False)
    _ev(s, sync_state="local")
    _ev(s, sync_state="pending_push")
    dead = _ev(s, sync_state="synced", external_event_id="evtX",
               external_calendar_id="cal1", is_active=False)
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: {"id": "new"} if m == "POST" else {})
    res = calendar_sync.sync_user_pending(s, 1)
    assert res["pushed"] == 2
    assert res["deleted"] == 1
    assert res["failed"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_sync.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.calendar_sync`).

- [ ] **Step 3: Create `calendar_sync.py`**

```python
# app/services/calendar_sync.py
"""Orchestrazione sync calendario Claqo ↔ Google — Fase C.

- maybe_autosync_event: hook on-save (push/delete immediato se toggle ON).
- sync_user_pending: push/delete in blocco di tutto il pending (bottone manuale).
Best-effort: nessuna eccezione propagata al CRUD locale.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.models import CalendarEvent
from app.services import google_calendar
from app.services.oauth_providers import get_token

log = logging.getLogger(__name__)


def maybe_autosync_event(db: Session, user_id, ev, deleted: bool = False) -> None:
    if not user_id:
        return
    row = get_token(db, user_id, "google")
    if not row or not row.auto_sync_calendar:
        return
    try:
        if deleted:
            google_calendar.delete_event(db, user_id, ev)
        else:
            ok = google_calendar.push_event(db, user_id, ev)
            if not ok and ev.sync_state == "error":
                ev.sync_state = "pending_push"
    except Exception as e:  # best-effort: non rompere il CRUD locale
        log.warning(f"maybe_autosync_event ev={getattr(ev, 'id', '?')}: {e}")
        ev.sync_state = "pending_push"
        ev.sync_error = str(e)[:500]


def sync_user_pending(db: Session, user_id: int) -> dict:
    pushed = deleted = failed = 0
    to_push = db.query(CalendarEvent).filter(
        CalendarEvent.owner_user_id == user_id,
        CalendarEvent.is_active == True,  # noqa: E712
        CalendarEvent.sync_state.in_(("local", "pending_push", "error")),
    ).all()
    for ev in to_push:
        if google_calendar.push_event(db, user_id, ev):
            pushed += 1
        else:
            failed += 1
    to_delete = db.query(CalendarEvent).filter(
        CalendarEvent.owner_user_id == user_id,
        CalendarEvent.is_active == False,  # noqa: E712
        CalendarEvent.external_event_id.isnot(None),
        CalendarEvent.sync_state != "deleted",
    ).all()
    for ev in to_delete:
        if google_calendar.delete_event(db, user_id, ev):
            deleted += 1
        else:
            failed += 1
    db.commit()
    return {"pushed": pushed, "deleted": deleted, "failed": failed}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_sync.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add app/services/calendar_sync.py tests/test_calendar_sync.py
git commit -F <msgfile>
# "feat(calendar): orchestrazione sync (autosync on-save + sync pending)"
```

---

### Task 3: Router — wiring autosync + endpoint sync/overlay + serializzazione

**Files:**
- Modify: `app/routers/calendar.py` (`_serialize_event` ~riga 37; `create_event`/`update_event`/`delete_event` ~riga 148-214; nuovi endpoint in fondo)
- Test: `tests/test_calendar_sync_api.py`

**Interfaces:**
- Consumes: `maybe_autosync_event`, `sync_user_pending` (Task 2); `google_calendar.list_google_events` (Task 1); `current_user_optional`.
- Produces:
  - `_serialize_event` include `sync_state`, `external_event_id`.
  - `POST /calendar/api/sync` → `{"pushed","deleted","failed"}`.
  - `GET /calendar/api/google-overlay?start&end` → `{"events": [...]}` (mai 500).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calendar_sync_api.py
from datetime import timedelta
from tests.test_calendar_api import client  # noqa: F401
from app.services.clock import now_utc


def test_serialize_includes_sync_fields(client):
    c, _ = client
    r = c.post("/calendar/api/events", data={"title": "Sync me",
               "start_at": "2026-07-10T10:00:00", "end_at": "2026-07-10T11:00:00"})
    assert r.status_code in (200, 201)
    body = r.json()
    assert "sync_state" in body and "external_event_id" in body


def test_sync_endpoint_ok_without_google(client):
    c, _ = client
    r = c.post("/calendar/api/sync")
    assert r.status_code == 200
    assert set(r.json().keys()) == {"pushed", "deleted", "failed"}


def test_overlay_empty_without_connection(client):
    c, _ = client
    r = c.get("/calendar/api/google-overlay", params={"start": "2026-07-01T00:00:00Z",
              "end": "2026-07-31T00:00:00Z"})
    assert r.status_code == 200
    assert r.json() == {"events": []}


def test_autosync_pushes_on_create(client, monkeypatch):
    c, s = client
    from app.models.models import UserOAuthToken
    from app.services import google_calendar as gc
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1),
                         auto_sync_calendar=True, claqo_calendar_id="cal1")); s.commit()
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: {"id": "evtZ"} if m == "POST" else {})
    r = c.post("/calendar/api/events", data={"title": "Auto",
               "start_at": "2026-07-10T10:00:00", "end_at": "2026-07-10T11:00:00"})
    assert r.json()["sync_state"] == "synced"
    assert r.json()["external_event_id"] == "evtZ"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_sync_api.py -v`
Expected: FAIL (campi assenti / 404 endpoint).

- [ ] **Step 3: Extend `_serialize_event`**

In `app/routers/calendar.py`, dentro `_serialize_event`, aggiungi le due chiavi prima della chiusura:

```python
        "attendees": ev.attendees or [], "source": ev.source,
        "sync_state": ev.sync_state, "external_event_id": ev.external_event_id,
    }
```

- [ ] **Step 4: Add the import**

In cima a `app/routers/calendar.py`, con gli altri import service:

```python
from app.services.calendar_sync import maybe_autosync_event, sync_user_pending
```

- [ ] **Step 5: Hook autosync nei CRUD**

In `create_event`, sostituisci `db.add(ev); db.commit(); db.refresh(ev)\n    return _serialize_event(ev)` con:

```python
    db.add(ev); db.commit(); db.refresh(ev)
    maybe_autosync_event(db, ev.owner_user_id, ev)
    db.commit(); db.refresh(ev)
    return _serialize_event(ev)
```

In `update_event`, sostituisci `db.commit(); db.refresh(ev)\n    return _serialize_event(ev)` con:

```python
    db.commit(); db.refresh(ev)
    maybe_autosync_event(db, ev.owner_user_id, ev)
    db.commit(); db.refresh(ev)
    return _serialize_event(ev)
```

In `delete_event`, sostituisci `ev.is_active = False\n    db.commit()\n    return {"ok": True}` con:

```python
    ev.is_active = False
    db.commit()
    maybe_autosync_event(db, ev.owner_user_id, ev, deleted=True)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 6: Add the sync + overlay endpoints**

In fondo a `app/routers/calendar.py`:

```python
@router.post("/calendar/api/sync", dependencies=[RequireManage])
async def sync_now(request: Request, db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u:
        raise HTTPException(401, "Non autenticato")
    return sync_user_pending(db, u.id)


@router.get("/calendar/api/google-overlay", dependencies=[RequireView])
async def google_overlay(start: Optional[str] = None, end: Optional[str] = None,
                         request: Request = None, db: Session = Depends(get_db)):
    u = current_user_optional(request)
    if not u or not start or not end:
        return {"events": []}
    from app.services import google_calendar
    try:
        return {"events": google_calendar.list_google_events(db, u.id, start, end)}
    except Exception:
        return {"events": []}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_sync_api.py tests/test_calendar_api.py -v`
Expected: PASS (4 nuovi + regressione Task 3 α.240 verde).

- [ ] **Step 8: Commit**

```bash
git add app/routers/calendar.py tests/test_calendar_sync_api.py
git commit -F <msgfile>
# "feat(calendar): autosync CRUD + endpoint sync/overlay + serializza sync_state"
```

---

### Task 4: Frontend — overlay Google + bottone Sincronizza + badge + i18n

**Files:**
- Modify: `app/static/js/calendar_page.js` (overlay + sync + badge)
- Modify: `app/templates/pages/calendar.html` (toolbar: checkbox + bottone; CSS `.cal-google`)
- Modify: `app/static/js/i18n.js` (chiavi `cal.sync.*`, `cal.showGoogle`, `cal.google.readonly`, `cal.synced`)
- Test: `tests/test_calendar_sync_page.py`

**Interfaces:**
- Consumes: `GET /calendar/api/google-overlay`, `POST /calendar/api/sync` (Task 3).
- Produces: pagina `/calendar` con `id="cal-show-google"`, bottone `calSyncNow()`; overlay eventi read-only con classe `cal-google`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_sync_page.py
import pathlib
from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_has_sync_ui(client):
    c, _ = client
    html = c.get("/calendar").text
    assert 'id="cal-show-google"' in html
    assert "calSyncNow" in html


def test_i18n_has_sync_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("cal.sync.now", "cal.sync.done", "cal.sync.error",
                "cal.showGoogle", "cal.google.readonly", "cal.synced"):
        assert key in src, key
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_sync_page.py -v`
Expected: FAIL (UI/chiavi assenti).

- [ ] **Step 3: Add i18n keys**

In `app/static/js/i18n.js`, dopo `'acq.appt.allDayLabel'` (o vicino alle `cal.*`):

```javascript
  'cal.sync.now':      {it: 'Sincronizza', en: 'Sync', fr: 'Synchroniser', de: 'Synchronisieren', es: 'Sincronizar'},
  'cal.sync.done':     {it: 'Sincronizzato', en: 'Synced', fr: 'Synchronise', de: 'Synchronisiert', es: 'Sincronizado'},
  'cal.sync.error':    {it: 'Errore sincronizzazione', en: 'Sync error', fr: 'Erreur de synchronisation', de: 'Sync-Fehler', es: 'Error de sincronizacion'},
  'cal.showGoogle':    {it: 'Mostra Google', en: 'Show Google', fr: 'Afficher Google', de: 'Google anzeigen', es: 'Mostrar Google'},
  'cal.google.readonly': {it: 'Evento Google (sola lettura)', en: 'Google event (read-only)', fr: 'Evenement Google (lecture seule)', de: 'Google-Termin (schreibgeschutzt)', es: 'Evento de Google (solo lectura)'},
  'cal.synced':        {it: 'Sincronizzato con Google', en: 'Synced with Google', fr: 'Synchronise avec Google', de: 'Mit Google synchronisiert', es: 'Sincronizado con Google'},
```

- [ ] **Step 4: Update `calendar.html` toolbar + CSS**

In `app/templates/pages/calendar.html`, sostituisci il blocco `.cal-toolbar` con:

```html
<div class="cal-toolbar">
  <select id="cal-scope" class="input">
    <option value="team" data-i18n="cal.filter.team">Team</option>
    <option value="mine" data-i18n="cal.filter.mine">Solo miei</option>
  </select>
  <label style="display:flex;align-items:center;gap:6px;font-size:13px;">
    <input type="checkbox" id="cal-show-google" checked> <span data-i18n="cal.showGoogle">Mostra Google</span>
  </label>
  <button class="btn btn-secondary" onclick="calSyncNow()" data-i18n="cal.sync.now">Sincronizza</button>
  <button class="btn btn-primary" onclick="calNewEvent()" data-i18n="cal.new">Nuovo appuntamento</button>
</div>
```

E nello `<style>` aggiungi:

```css
  .cal-google { opacity:.55; border:1px solid var(--text3, #888) !important; }
  .fc-event.cal-synced::after { content:'⟲'; margin-left:4px; font-size:10px; opacity:.8; }
```

- [ ] **Step 5: Update `calendar_page.js`**

In `calFetchEvents` (dopo aver mappato `evs` dai `data.events`, prima dei markers), aggiungi il badge synced e poi l'overlay Google. Sostituisci il corpo di `calFetchEvents` con:

```javascript
async function calFetchEvents(info, success, failure) {
  try {
    const url = '/calendar/api/events?start=' + encodeURIComponent(info.startStr) +
                '&end=' + encodeURIComponent(info.endStr) + '&scope=' + calScope();
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const evs = (data.events || []).map(e => ({
      id: e.id, title: e.title, start: e.start, end: e.end, allDay: e.all_day,
      classNames: e.external_event_id ? ['cal-synced'] : [],
      extendedProps: {
        source: e.source, description: e.description, location: e.location,
        meeting_url: e.meeting_url, status: e.status, sync_state: e.sync_state,
        acquisition_id: e.acquisition_id, client_id: e.client_id, project_id: e.project_id
      }
    }));
    (data.markers || []).forEach(m => evs.push({
      title: '• ' + m.title, start: m.date, allDay: true, display: 'background',
      classNames: ['cal-marker'], editable: false, extendedProps: { marker: m.kind }
    }));
    // Overlay Google read-only (best-effort, non blocca)
    const showG = document.getElementById('cal-show-google');
    if (showG && showG.checked) {
      try {
        const gr = await fetch('/calendar/api/google-overlay?start=' +
          encodeURIComponent(info.startStr) + '&end=' + encodeURIComponent(info.endStr));
        if (gr.ok) {
          const gd = await gr.json();
          (gd.events || []).forEach(g => evs.push({
            title: g.title, start: g.start, end: g.end, allDay: g.all_day,
            editable: false, classNames: ['cal-google'],
            extendedProps: { google: true }
          }));
        }
      } catch (e) { /* overlay best-effort */ }
    }
    success(evs);
  } catch (e) { failure(e); }
}
```

In `eventClick`, ignora anche gli eventi Google (oltre ai marker):

```javascript
    eventClick: function (info) {
      if (info.event.extendedProps.marker || info.event.extendedProps.google) return;
      info.jsEvent.preventDefault();
      window.openEventModal({ event: _fcEventToObj(info.event), onSaved: () => _cal.refetchEvents() });
    },
```

Aggiungi la funzione `calSyncNow` (dopo `calNewEvent`):

```javascript
async function calSyncNow() {
  try {
    const r = await fetch('/calendar/api/sync', { method: 'POST' });
    const d = await r.json();
    if (r.ok && window.toast) {
      toast(mfT('cal.sync.done') + ': ' + (d.pushed || 0) + '↑ ' + (d.deleted || 0) + '✕' +
            (d.failed ? ' · ' + d.failed + ' ' + mfT('cal.sync.error') : ''), d.failed ? 'error' : 'success');
    } else if (!r.ok && window.toast) {
      toast(mfT('cal.sync.error'), 'error');
    }
  } catch (e) {
    if (window.toast) toast(mfT('cal.sync.error'), 'error');
  }
  if (_cal) _cal.refetchEvents();
}
```

E aggancia il refetch al checkbox (nel blocco `DOMContentLoaded`, vicino al listener di `cal-scope`):

```javascript
  const shg = document.getElementById('cal-show-google');
  if (shg) shg.addEventListener('change', () => _cal.refetchEvents());
```

- [ ] **Step 6: Run test + JS syntax + grep guard**

Run: `.venv/Scripts/python.exe -m pytest tests/test_calendar_sync_page.py -v`
Expected: PASS (2 passed).
Run: `node --check app/static/js/calendar_page.js`
Expected: nessun errore.
Run: `grep -n "calSyncNow\|cal-show-google\|cal-google" app/static/js/calendar_page.js app/templates/pages/calendar.html`
Expected: definite/referenziate.

- [ ] **Step 7: Commit**

```bash
git add app/static/js/calendar_page.js app/templates/pages/calendar.html app/static/js/i18n.js tests/test_calendar_sync_page.py
git commit -F <msgfile>
# "feat(calendar): overlay Google read-only + bottone Sincronizza + badge synced"
```

---

### Task 5: Chiusura fase — bump versione + suite + smoke

**Files:**
- Modify: `app/main.py` (`.241` → `.242`), `CHANGELOG.md`, `docs/STATO.md`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: versione `3.5.0-alpha.172.242`.

- [ ] **Step 1: Bump version**

In `app/main.py`: `version="3.5.0-alpha.172.241"` → `"3.5.0-alpha.172.242"`.

- [ ] **Step 2: CHANGELOG**

In `CHANGELOG.md`, nuova voce in cima:

```markdown
## v3.5.0-alpha.172.242 — Fase C Calendario: sync Google bidirezionale (6 lug 2026)

- **Push per-utente** degli appuntamenti Claqo verso un calendario secondario "Claqo" nell'account Google dell'utente (`calendar.app.created`): create/edit/delete si riflettono su Google.
- **Overlay read-only** degli eventi Google esistenti dentro `/calendar` (`calendar.readonly`, esclude il calendario Claqo), con checkbox "Mostra Google".
- **Autosync** on-save se `auto_sync_calendar` ON + bottone **"Sincronizza"** (push/delete di tutto il pending). Badge ⟲ sugli eventi sincronizzati.
- `app/services/google_calendar.py` (client API, urllib, mockabile) + `app/services/calendar_sync.py` (orchestrazione). Endpoint `POST /calendar/api/sync`, `GET /calendar/api/google-overlay`. Best-effort: nessuna chiamata Google blocca il CRUD locale o il render.
- Nessuna migrazione DB (colonne sync già presenti). Testato con mock httpx; live appena l'utente configura l'OAuth client Google Cloud.
```

- [ ] **Step 3: STATO**

In `docs/STATO.md`: versione corrente → `.242`; sezione `### α.172.242 ✅ (Fase C sync Google — 6 lug)` coi punti sopra; **Prossimo step** → Fase D documenti (Drive) oppure rifinitura sync (gestione conflitti avanzata / webhook) se richiesta.

- [ ] **Step 4: Full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q`
Expected: tutti verdi (1053 + nuovi). Se un test preesistente rompe, correggilo minimamente e annota.

- [ ] **Step 5: Smoke browser (Playwright, mock server-side)**

Avvia server. Con token Google assente (caso reale senza credenziali): `/calendar` carica, overlay vuoto, bottone "Sincronizza" → toast `0↑ 0✕`, checkbox "Mostra Google" togglabile, 0 errori console. Verifica che create/edit/delete locali continuino a funzionare (autosync no-op senza connessione).

- [ ] **Step 6: Commit**

```bash
git add app/main.py CHANGELOG.md docs/STATO.md
git commit -F <msgfile>
# "chore(calendar): Fase C v3.5.0-alpha.172.242 (sync Google)"
```

---

## Self-Review

**1. Spec coverage:**
- `google_calendar.py` (ensure/push/delete/list + helpers) → Task 1 ✓
- `calendar_sync.py` (maybe_autosync_event + sync_user_pending) → Task 2 ✓
- Wiring CRUD autosync via `ev.owner_user_id` → Task 3 ✓
- `POST /calendar/api/sync`, `GET /calendar/api/google-overlay` → Task 3 ✓
- `_serialize_event` con sync_state + external_event_id → Task 3 ✓
- Overlay read-only + checkbox + bottone Sincronizza + badge → Task 4 ✓
- i18n 5 lingue → Task 4 ✓
- Nessuna migrazione, best-effort, per-utente, scope least-privilege → vincoli rispettati in Task 1/2/3 ✓
- Testing mock httpx + smoke → Task 1/2/3/4/5 ✓

**2. Placeholder scan:** nessun TBD/TODO; ogni step di codice mostra il codice.

**3. Type consistency:** `ensure_claqo_calendar`/`push_event`/`delete_event`/`list_google_events`/`_google_request`/`maybe_autosync_event`/`sync_user_pending` coerenti tra Task 1/2/3 e i test. `sync_state` valori (`local`/`synced`/`pending_push`/`error`/`deleted`) coerenti. Chiavi frontend `cal.sync.*` coerenti Task 4. `_google_request` firma `(method, url, token, body=None, params=None)` identica in impl e mock dei test.

## Note

- Il mock nei test sostituisce `google_calendar._google_request`, quindi nessuna rete reale. `get_valid_access_token` con `expires_at` futuro ritorna il token senza refresh (nessuna chiamata di rete).
- `maybe_autosync_event` usa `ev.owner_user_id`: il sync va sull'account Google del proprietario dell'evento, non necessariamente dell'utente che fa la modifica.
- Timezone: gli ISO naive di Claqo vengono passati come `dateTime` senza offset; Google li interpreta nel fuso del calendario. Normalizzazione tz fine fuori scope (coerente con Fase B).
