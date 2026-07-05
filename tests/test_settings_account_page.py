"""Smoke tests — Task 6: tab Account collegati (OAuth linking) in /settings."""
from tests.test_acquisitions_api import client  # noqa: F401


def test_settings_page_has_account_tab(client):
    c, _ = client
    html = c.get("/settings/").text
    assert 'data-i18n="settings.account.title"' in html
    # il tab account deve referenziare lo script dedicato
    assert "settings_account.js" in html


def test_i18n_has_account_keys():
    """Tutti i 13 tasti settings.account.* devono esistere in i18n.js."""
    import pathlib
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    required_keys = [
        "settings.account.title",
        "settings.account.connect",
        "settings.account.disconnect",
        "settings.account.notLinked",
        "settings.account.autoSync",
        "settings.account.comingSoon",
        "settings.account.connected",
        "settings.account.noProviders",
        "settings.account.desc",
        "settings.account.confirmDisconnect",
        "settings.account.disconnected",
        "settings.account.syncUpdated",
        "settings.account.notConfigured",
    ]
    for key in required_keys:
        assert key in src, f"Chiave i18n mancante: {key}"
    for lang in ("it", "en", "fr", "de", "es"):
        # sanity: ogni lingua compare almeno una volta nel file
        assert f"{lang}:" in src
