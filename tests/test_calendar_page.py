# tests/test_calendar_page.py
from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_renders(client):
    c, _ = client
    html = c.get("/calendar").text
    assert 'id="calendar-root"' in html
    assert "calendar_page.js" in html
    assert 'data-i18n="nav.calendar"' in html or 'data-i18n="cal.title"' in html


def test_i18n_has_calendar_keys():
    import pathlib
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("nav.calendar", "cal.title", "cal.new", "cal.event.title", "cal.event.save"):
        assert key in src, key
