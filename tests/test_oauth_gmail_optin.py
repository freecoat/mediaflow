import urllib.parse
from app.services import oauth_providers as oauth


def _params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_gmail_scopes_constant():
    assert "gmail.readonly" in oauth.GMAIL_SCOPES
    assert "gmail.compose" in oauth.GMAIL_SCOPES


def test_authorization_url_default_no_gmail_read():
    url = oauth.authorization_url("google", "st")
    scope = _params(url)["scope"]
    assert "gmail.readonly" not in scope          # opt-in: non nel bundle di default
    assert "include_granted_scopes" not in _params(url)


def test_authorization_url_with_extra_scopes():
    url = oauth.authorization_url("google", "st", extra_scopes=oauth.GMAIL_SCOPES)
    p = _params(url)
    assert "gmail.readonly" in p["scope"]
    assert "gmail.compose" in p["scope"]
    assert p["include_granted_scopes"] == "true"
    # gli scope base restano presenti
    assert "calendar.app.created" in p["scope"]
