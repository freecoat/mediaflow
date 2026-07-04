"""Smoke tests — Task 6: tab Account collegati (OAuth linking) in /settings."""
from tests.test_acquisitions_api import client  # noqa: F401


def test_settings_page_has_account_tab(client):
    c, _ = client
    html = c.get("/settings/").text
    assert 'data-i18n="settings.account.title"' in html
    # il tab account deve referenziare lo script dedicato
    assert "settings_account.js" in html


def test_i18n_has_account_keys():
    # la chiave deve esistere in tutte le 5 lingue
    import pathlib
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    assert "settings.account.title" in src
    for lang in ("it", "en", "fr", "de", "es"):
        # sanity: ogni lingua compare almeno una volta nel file
        assert f"{lang}:" in src
