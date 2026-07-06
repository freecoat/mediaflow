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
