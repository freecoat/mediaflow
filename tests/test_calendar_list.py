"""Sotto-fase 1 — lista calendari Google (sidebar 'I miei calendari')."""
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
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


def test_list_calendars_maps_fields(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gc, "_google_request", lambda m, u, t, body=None, params=None: {
        "items": [
            {"id": "primary", "summary": "Io", "backgroundColor": "#abc",
             "accessRole": "owner", "primary": True},
            {"id": "work@g.com", "summary": "Lavoro", "backgroundColor": "#def",
             "accessRole": "writer"}]})
    out = gc.list_calendars(s, 1)
    assert len(out) == 2
    p = next(c for c in out if c["id"] == "primary")
    assert p["summary"] == "Io" and p["color"] == "#abc"
    assert p["access_role"] == "owner" and p["primary"] is True
    assert next(c for c in out if c["id"] == "work@g.com")["primary"] is False


def test_list_calendars_excludes_claqo(monkeypatch):
    s = _session(); _connect(s, cal_id="claqo@g.com")
    monkeypatch.setattr(gc, "_google_request", lambda m, u, t, body=None, params=None: {
        "items": [{"id": "claqo@g.com", "summary": "Claqo", "accessRole": "owner"},
                  {"id": "work@g.com", "summary": "Lavoro", "accessRole": "owner"}]})
    out = gc.list_calendars(s, 1)
    assert [c["id"] for c in out] == ["work@g.com"]


def test_list_calendars_no_token():
    s = _session()  # nessun token
    assert gc.list_calendars(s, 1) == []


def test_list_calendars_best_effort_on_error(monkeypatch):
    s = _session(); _connect(s)

    def boom(m, u, t, body=None, params=None):
        raise RuntimeError("api down")
    monkeypatch.setattr(gc, "_google_request", boom)
    assert gc.list_calendars(s, 1) == []
