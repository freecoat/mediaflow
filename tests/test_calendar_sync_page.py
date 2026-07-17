import pathlib
from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_has_sync_ui(client):
    c, _ = client
    html = c.get("/calendar").text
    # α.248: singolo checkbox "Mostra Google" sostituito dalla sidebar "I miei calendari".
    assert 'id="cal-list"' in html
    assert 'data-i18n="cal.myCalendars"' in html
    assert "calSyncNow" in html


def test_i18n_has_sync_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("cal.sync.now", "cal.sync.done", "cal.sync.error",
                "cal.myCalendars", "cal.claqoCalendar", "cal.noCalendars",
                "cal.google.readonly", "cal.synced"):
        assert key in src, key
