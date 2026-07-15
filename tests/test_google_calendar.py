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


def test_ensure_returns_none_on_api_error(monkeypatch):
    # Token presente ma claqo_calendar_id NULL → ensure crea il calendario via API.
    # Se l'API fallisce (token revocato/scaduto → 403), best-effort: None, mai raise.
    s = _session(); _connect(s)  # cal_id=None
    def boom(*a, **k): raise RuntimeError("HTTP 403: Forbidden")
    monkeypatch.setattr(gc, "_google_request", boom)
    assert gc.ensure_claqo_calendar(s, 1) is None


def test_push_no_raise_when_ensure_fails(monkeypatch):
    # Regressione: prima ensure_claqo_calendar (fuori dal try di push_event)
    # propagava la HTTPError → 500 su /calendar/api/sync. Ora push_event ritorna
    # False senza sollevare.
    s = _session(); _connect(s)  # cal_id=None → ensure chiama l'API
    ev = _ev(s)
    def boom(*a, **k): raise RuntimeError("HTTP 403: Forbidden")
    monkeypatch.setattr(gc, "_google_request", boom)
    assert gc.push_event(s, 1, ev) is False
    assert ev.sync_state != "synced"


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


# ── Eventi Google editabili (design 2026-07-15) ──────────────────────────

import urllib.error as _urlerr


def test_google_request_passes_extra_headers(monkeypatch):
    """If-Match per il conflict detection deve arrivare negli header HTTP."""
    captured = {}

    class _FakeReq:
        def __init__(self, url, data=None, method=None, headers=None):
            captured["headers"] = headers
            captured["method"] = method

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"{}"

    monkeypatch.setattr("urllib.request.Request", _FakeReq)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=15: _FakeResp())
    gc._google_request("PATCH", "https://x", "tok", extra_headers={"If-Match": "abc123"})
    assert captured["headers"]["If-Match"] == "abc123"
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_has_calendar_write_scope_true_for_events_scope():
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="openid https://www.googleapis.com/auth/calendar.events")
    assert gc.has_calendar_write_scope(row) is True


def test_has_calendar_write_scope_true_for_full_calendar_superset():
    """Caso reale osservato: alcuni token hanno lo scope 'calendar' pieno, superset di events."""
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="openid https://www.googleapis.com/auth/calendar")
    assert gc.has_calendar_write_scope(row) is True


def test_has_calendar_write_scope_false_for_readonly_only():
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="https://www.googleapis.com/auth/calendar.readonly "
                                "https://www.googleapis.com/auth/calendar.app.created")
    assert gc.has_calendar_write_scope(row) is False


def test_has_calendar_write_scope_false_when_no_row():
    assert gc.has_calendar_write_scope(None) is False


def test_normalize_editable_true_for_writer_with_scope():
    g = {"id": "e1", "summary": "X", "start": {"dateTime": "2026-07-10T09:00:00Z"},
         "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "writer", True)
    assert out["editable"] is True
    assert out["calendar_id"] == "cal1"
    assert out["access_role"] == "writer"
    assert out["read_only"] is False


def test_normalize_editable_false_for_reader():
    """Calendari condivisi/festivi (es. Kalenderwochen) non devono mai risultare editabili."""
    g = {"id": "e1", "summary": "X", "start": {"date": "2026-07-10"}, "end": {"date": "2026-07-11"}}
    out = gc._normalize_google_event(g, "Kalenderwochen", "cal2", "reader", True)
    assert out["editable"] is False
    assert out["read_only"] is True


def test_normalize_editable_false_without_write_scope():
    g = {"id": "e1", "summary": "X", "start": {"dateTime": "2026-07-10T09:00:00Z"},
         "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "owner", False)
    assert out["editable"] is False


def test_normalize_editable_false_for_recurring_master():
    g = {"id": "e1", "summary": "X", "recurrence": ["RRULE:FREQ=WEEKLY"],
         "start": {"dateTime": "2026-07-10T09:00:00Z"}, "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "owner", True)
    assert out["editable"] is False


def test_normalize_editable_false_for_recurring_instance():
    g = {"id": "e1_20260710", "summary": "X", "recurringEventId": "e1",
         "start": {"dateTime": "2026-07-10T09:00:00Z"}, "end": {"dateTime": "2026-07-10T10:00:00Z"}}
    out = gc._normalize_google_event(g, "Lavoro", "cal1", "owner", True)
    assert out["editable"] is False


def _fake_cal_list(m, url, t, body=None, params=None, extra_headers=None):
    if url.endswith("/users/me/calendarList"):
        return {"items": [
            {"id": "claqoCal", "summary": "Claqo", "accessRole": "owner"},
            {"id": "mine", "summary": "Personale", "accessRole": "owner"},
            {"id": "readonly-cal", "summary": "Kalenderwochen", "accessRole": "reader"},
        ]}
    if "/calendars/mine/events" in url:
        return {"items": [{"id": "g1", "summary": "Riunione",
                           "start": {"dateTime": "2026-07-10T09:00:00Z"},
                           "end": {"dateTime": "2026-07-10T10:00:00Z"}}]}
    if "/calendars/readonly-cal/events" in url:
        return {"items": [{"id": "g2", "summary": "Ferragosto",
                           "start": {"date": "2026-08-15"}, "end": {"date": "2026-08-16"}}]}
    return {"items": []}


def test_list_google_events_propagates_access_role(monkeypatch):
    s = _session(); _connect(s, cal_id="claqoCal")
    row = s.query(UserOAuthToken).filter_by(user_id=1, provider="google").first()
    row.scopes = "https://www.googleapis.com/auth/calendar.events"
    s.commit()
    monkeypatch.setattr(gc, "_google_request", _fake_cal_list)
    out = gc.list_google_events(s, 1, "2026-07-01T00:00:00Z", "2026-08-31T00:00:00Z")
    by_id = {e["id"]: e for e in out}
    assert by_id["g1"]["editable"] is True
    assert by_id["g2"]["editable"] is False  # accessRole=reader


def test_list_google_events_not_editable_without_optin(monkeypatch):
    """Senza opt-in scrittura nessun evento e' editabile, anche se owner."""
    s = _session(); _connect(s, cal_id="claqoCal")
    row = s.query(UserOAuthToken).filter_by(user_id=1, provider="google").first()
    row.scopes = "https://www.googleapis.com/auth/calendar.readonly"
    s.commit()
    monkeypatch.setattr(gc, "_google_request", _fake_cal_list)
    out = gc.list_google_events(s, 1, "2026-07-01T00:00:00Z", "2026-08-31T00:00:00Z")
    assert all(e["editable"] is False for e in out)


def test_get_external_event_returns_normalized_with_etag(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {
            "id": "evt1", "summary": "Riunione", "etag": '"abc123"',
            "start": {"dateTime": "2026-07-10T09:00:00Z"},
            "end": {"dateTime": "2026-07-10T10:00:00Z"}})
    ev = gc.get_external_event(s, 1, "cal1", "evt1")
    assert ev["title"] == "Riunione"
    assert ev["etag"] == '"abc123"'


def test_get_external_event_none_without_connection():
    assert gc.get_external_event(_session(), 1, "cal1", "evt1") is None


def test_update_external_event_sends_patch_with_if_match(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    seen = {}

    def fake(m, u, t, body=None, params=None, extra_headers=None):
        seen["method"] = m; seen["headers"] = extra_headers; seen["body"] = body
        return {"id": "evt1", "summary": body["summary"]}

    monkeypatch.setattr(gc, "_google_request", fake)
    res = gc.update_external_event(s, 1, "cal1", "evt1", title="Nuovo titolo",
                                   start_at="2026-07-10T09:00:00", end_at="2026-07-10T10:00:00",
                                   etag='"abc123"')
    assert res["ok"] is True
    assert seen["method"] == "PATCH", "PATCH, non PUT: non azzerare i campi non modellati da Claqo"
    assert seen["headers"] == {"If-Match": '"abc123"'}
    assert seen["body"]["summary"] == "Nuovo titolo"


def test_update_external_event_conflict_412(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")

    def boom(*a, **k):
        raise _urlerr.HTTPError("url", 412, "Precondition Failed", {}, None)

    monkeypatch.setattr(gc, "_google_request", boom)
    res = gc.update_external_event(s, 1, "cal1", "evt1", title="X", etag='"stale"')
    assert res["ok"] is False
    assert res["http_status"] == 412
    assert res["error"] == "conflict"


def test_update_external_event_forbidden_403(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")

    def boom(*a, **k):
        raise _urlerr.HTTPError("url", 403, "Forbidden", {}, None)

    monkeypatch.setattr(gc, "_google_request", boom)
    res = gc.update_external_event(s, 1, "cal1", "evt1", title="X")
    assert res["ok"] is False
    assert res["error"] == "forbidden"


def test_update_external_event_not_connected():
    res = gc.update_external_event(_session(), 1, "cal1", "evt1", title="X")
    assert res["ok"] is False
    assert res["error"] == "not_connected"


def test_delete_external_event_ok(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")
    seen = {}
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: seen.setdefault("m", m))
    res = gc.delete_external_event(s, 1, "cal1", "evt1")
    assert res["ok"] is True
    assert seen["m"] == "DELETE"


def test_delete_external_event_404_is_idempotent_success(monkeypatch):
    s = _session(); _connect(s, cal_id="cal1")

    def boom(*a, **k):
        raise _urlerr.HTTPError("url", 404, "Not Found", {}, None)

    monkeypatch.setattr(gc, "_google_request", boom)
    assert gc.delete_external_event(s, 1, "cal1", "evt1")["ok"] is True


def test_delete_external_event_not_connected():
    res = gc.delete_external_event(_session(), 1, "cal1", "evt1")
    assert res["ok"] is False
    assert res["error"] == "not_connected"
