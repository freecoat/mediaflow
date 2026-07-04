from app.services import oauth_providers as oauth


def test_google_scopes_include_calendar_and_drive():
    scopes = oauth.PROVIDERS["google"]["scopes"]
    assert "https://www.googleapis.com/auth/calendar" in scopes
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert "email" in scopes and "profile" in scopes


def test_google_authorization_url_forces_offline_consent():
    url = oauth.authorization_url("google", "state123")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "calendar" in url  # scope url-encoded contiene calendar
