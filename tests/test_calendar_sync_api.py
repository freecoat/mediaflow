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
