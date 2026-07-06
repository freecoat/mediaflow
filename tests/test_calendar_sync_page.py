import pathlib
from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_has_sync_ui(client):
    c, _ = client
    html = c.get("/calendar").text
    assert 'id="cal-show-google"' in html
    assert "calSyncNow" in html


def test_i18n_has_sync_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("cal.sync.now", "cal.sync.done", "cal.sync.error",
                "cal.showGoogle", "cal.google.readonly", "cal.synced"):
        assert key in src, key
