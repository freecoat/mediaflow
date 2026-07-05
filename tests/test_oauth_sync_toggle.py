from tests.test_acquisitions_api import client  # noqa: F401
from app.models.models import UserOAuthToken


def test_status_includes_sync_fields(client):
    c, _ = client
    st = c.get("/auth/oauth/status").json()
    assert "google" in st["providers"]
    assert "auto_sync_calendar" in st["providers"]["google"]


def test_sync_toggle_requires_connection(client):
    c, _ = client
    r = c.post("/auth/oauth/google/sync-toggle", data={"enabled": "true"})
    assert r.status_code == 404


def test_sync_toggle_flips_flag(client):
    c, s = client
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="at",
                         auto_sync_calendar=False)); s.commit()
    r = c.post("/auth/oauth/google/sync-toggle", data={"enabled": "true"})
    assert r.status_code == 200
    assert r.json()["auto_sync_calendar"] is True
    s.refresh(s.query(UserOAuthToken).filter_by(user_id=1, provider="google").first())
    assert s.query(UserOAuthToken).filter_by(user_id=1, provider="google").first().auto_sync_calendar is True
