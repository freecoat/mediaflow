# tests/test_oauth_router_state.py — riusa la fixture client dal file acquisitions
from tests.test_acquisitions_api import client  # noqa: F401
from app.services import oauth_providers as oauth


def test_start_with_calendar_write_includes_extra_scope(client):
    """?scopes=calendar_write → opt-in incrementale editing calendario (α.172.249)."""
    c, _ = client
    r = c.get("/auth/oauth/google/start?scopes=calendar_write", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert "calendar.events" in loc
    assert "include_granted_scopes=true" in loc


def test_start_without_scopes_param_excludes_calendar_write(client):
    c, _ = client
    r = c.get("/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "calendar.events" not in r.headers["location"]


def test_start_with_email_scope_non_regredisce(client):
    """L'opt-in Gmail preesistente resta intatto e non porta scope calendario."""
    c, _ = client
    r = c.get("/auth/oauth/google/start?scopes=email", follow_redirects=False)
    loc = r.headers["location"]
    # α.172.262: opt-in Gmail esteso a gmail.modify (supersede readonly) per le feature
    # mail-client mergiate dal ramo (etichette/filtri/vacation CRUD). Nessuno scope
    # calendario deve trapelare da un opt-in solo-email.
    assert "gmail.modify" in loc
    assert "calendar.events" not in loc


def test_start_with_mail_full_includes_extra_scope(client):
    """?scopes=mail_full → opt-in scope pieno per elimina-definitivo (α.172.263)."""
    c, _ = client
    r = c.get("/auth/oauth/google/start?scopes=mail_full", follow_redirects=False)
    assert r.status_code in (302, 307)
    loc = r.headers["location"]
    assert "mail.google.com" in loc
    assert "include_granted_scopes=true" in loc


def test_start_without_scopes_param_excludes_mail_full(client):
    c, _ = client
    r = c.get("/auth/oauth/google/start", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "mail.google.com" not in r.headers["location"]


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
