"""α.172.247 — attendees + edit/delete eventi Google esistenti (scope full)."""
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


def _connect(s, cal_id=None):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1), claqo_calendar_id=cal_id))
    s.commit()


def _ev(s, **kw):
    base = dict(tenant_id=1, title="X", start_at=datetime(2026, 7, 10, 10, 0),
                end_at=datetime(2026, 7, 10, 11, 0), owner_user_id=1)
    base.update(kw)
    ev = CalendarEvent(**base)
    s.add(ev); s.commit(); s.refresh(ev)
    return ev


def test_event_to_google_includes_attendees():
    s = _session()
    ev = _ev(s, attendees=["a@x.com", "b@y.com"], description="d")
    body = gc._event_to_google(ev)
    assert body["attendees"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]


def test_push_event_sendupdates_when_attendees(monkeypatch):
    s = _session(); _connect(s, cal_id="claqo")
    ev = _ev(s, attendees=["a@x.com"])
    calls = []
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: (calls.append(params), {"id": "E1"})[1])
    assert gc.push_event(s, 1, ev) is True
    assert calls[-1] == {"sendUpdates": "all"}


def test_update_google_event_patches(monkeypatch):
    s = _session(); _connect(s)
    calls = []
    monkeypatch.setattr(gc, "_google_request",
                        lambda m, u, t, body=None, params=None: (calls.append((m, u, params)), {"id": "E1"})[1])
    res = gc.update_google_event(s, 1, "cal@g.com", "E1",
                                 {"summary": "new", "attendees": [{"email": "x@x.com"}]})
    assert res["id"] == "E1"
    assert calls[0][0] == "PATCH"
    assert calls[0][2] == {"sendUpdates": "all"}


def test_delete_google_event_idempotent_404(monkeypatch):
    import urllib.error
    s = _session(); _connect(s)

    def boom(m, u, t, body=None, params=None):
        raise urllib.error.HTTPError(u, 404, "gone", {}, None)
    monkeypatch.setattr(gc, "_google_request", boom)
    assert gc.delete_google_event(s, 1, "cal", "E1") is True


def test_list_google_events_editable_flag(monkeypatch):
    s = _session(); _connect(s)

    def fake(m, u, t, body=None, params=None):
        if u.endswith("/calendarList"):
            return {"items": [
                {"id": "c1", "summary": "Work", "accessRole": "owner", "backgroundColor": "#fff"},
                {"id": "c2", "summary": "Holidays", "accessRole": "reader"}]}
        return {"items": [{"id": "E1", "summary": "Ev",
                           "start": {"dateTime": "2026-07-10T10:00:00Z"},
                           "end": {"dateTime": "2026-07-10T11:00:00Z"}}]}
    monkeypatch.setattr(gc, "_google_request", fake)
    out = gc.list_google_events(s, 1, "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z")
    byc = {e["calendar"]: e for e in out}
    assert byc["Work"]["read_only"] is False
    assert byc["Work"]["calendar_id"] == "c1"
    assert byc["Holidays"]["read_only"] is True
