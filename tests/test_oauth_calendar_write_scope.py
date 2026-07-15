"""Opt-in scope scrittura calendario (α.172.248).

Design 2026-07-15, Domanda 1: `calendar.events` (non `calendar` pieno, che darebbe
anche la gestione dei calendari) richiesto SOLO su opt-in esplicito, stesso pattern
già in produzione per GMAIL_SCOPES. Chi non lo attiva non subisce re-consent.
"""
import urllib.parse

from app.services import oauth_providers as oauth


def _params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


def test_calendar_write_scopes_constant():
    assert "calendar.events" in oauth.CALENDAR_WRITE_SCOPES


def test_calendar_write_non_chiede_calendar_pieno():
    """Least-privilege: calendar.events, mai lo scope 'calendar' pieno."""
    scopes = oauth.CALENDAR_WRITE_SCOPES.split()
    assert not any(s.endswith("/auth/calendar") for s in scopes)


def test_authorization_url_default_no_calendar_write():
    url = oauth.authorization_url("google", "st")
    assert "calendar.events" not in _params(url)["scope"]  # opt-in: non nel default


def test_authorization_url_with_calendar_write_extra_scope():
    url = oauth.authorization_url("google", "st", extra_scopes=oauth.CALENDAR_WRITE_SCOPES)
    p = _params(url)
    assert "calendar.events" in p["scope"]
    assert p["include_granted_scopes"] == "true"
    # gli scope base restano (bundle least-privilege invariato)
    assert "calendar.readonly" in p["scope"]
    assert "calendar.app.created" in p["scope"]
