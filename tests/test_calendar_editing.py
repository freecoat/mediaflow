import pathlib
from tests.test_calendar_api import client  # noqa: F401


def test_i18n_has_event_modal_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("cal.event.allday", "cal.event.status", "cal.event.status.confirmed",
                "cal.event.status.tentative", "cal.event.status.cancelled",
                "cal.event.cancel", "cal.event.new", "cal.event.edit",
                "cal.event.deleteConfirm", "cal.event.linkedTo", "cal.event.saved",
                "cal.event.err.title", "cal.event.err.range"):
        assert key in src, key


def test_calendar_page_includes_event_modal(client):
    c, _ = client
    html = c.get("/calendar").text
    assert "event_modal.js" in html


def test_acquisitions_includes_event_modal(client):
    c, _ = client
    html = c.get("/acquisitions").text
    assert "event_modal.js" in html
    assert 'id="det-tab-calendar"' in html
