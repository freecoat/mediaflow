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
    _ev(s, sync_state="synced", external_event_id="evtX",
        external_calendar_id="cal1", is_active=False)
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: {"id": "new"} if m == "POST" else {})
    res = calendar_sync.sync_user_pending(s, 1)
    assert res["pushed"] == 2
    assert res["deleted"] == 1
    assert res["failed"] == 0
