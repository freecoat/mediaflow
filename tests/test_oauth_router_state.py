# tests/test_oauth_router_state.py — riusa la fixture client dal file acquisitions
from tests.test_acquisitions_api import client  # noqa: F401
from app.services import oauth_providers as oauth


def test_callback_rejects_bad_state(client):
    c, _ = client
    r = c.get("/auth/oauth/google/callback?code=x&state=forged.deadbeef",
              follow_redirects=False)
    assert r.status_code == 400
    assert "state" in r.text.lower()


def test_callback_accepts_valid_state(client, monkeypatch):
    c, s = client
    # user id 1 esiste nella fixture
    state = oauth.make_oauth_state(1, "google")
    monkeypatch.setattr(oauth, "exchange_code_for_token",
                        lambda p, code: {"access_token": "at", "expires_in": 3600})
    monkeypatch.setattr(oauth, "fetch_userinfo",
                        lambda p, at: {"email": "linked@gmail.com"})
    r = c.get(f"/auth/oauth/google/callback?code=x&state={state}",
              follow_redirects=False)
    assert r.status_code == 200
    assert "linked@gmail.com" in r.text
    assert oauth.get_token(s, 1, "google") is not None
