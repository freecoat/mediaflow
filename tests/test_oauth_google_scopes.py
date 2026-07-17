from app.services import oauth_providers as oauth


def test_google_scopes_include_calendar_and_drive():
    scopes = oauth.PROVIDERS["google"]["scopes"]
    # α.172.262 (merge): bundle base least-privilege. La scrittura eventi Google è
    # opt-in via CALENDAR_WRITE_SCOPES (calendar.events), MAI `calendar` pieno nel
    # default — l'architettura opt-in di main vince sul ramo (che usava full calendar).
    assert "calendar.app.created" in scopes
    assert "calendar.readonly" in scopes
    assert "/auth/calendar\"" not in scopes  # nessuno scope 'calendar' pieno
    assert not scopes.rstrip().endswith("/auth/calendar")
    assert "https://www.googleapis.com/auth/drive.file" in scopes
    assert "gmail.send" in scopes
    assert "email" in scopes and "profile" in scopes


def test_google_authorization_url_forces_offline_consent():
    url = oauth.authorization_url("google", "state123")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "calendar" in url  # scope url-encoded contiene calendar (app.created o readonly)
