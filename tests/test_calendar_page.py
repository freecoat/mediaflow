# tests/test_calendar_page.py
import pathlib

from tests.test_calendar_api import client  # noqa: F401


def test_calendar_page_renders(client):
    c, _ = client
    html = c.get("/calendar").text
    assert 'id="calendar-root"' in html
    assert "calendar_page.js" in html
    assert 'data-i18n="nav.calendar"' in html or 'data-i18n="cal.title"' in html


def test_i18n_has_calendar_keys():
    src = pathlib.Path("app/static/js/i18n.js").read_text(encoding="utf-8")
    for key in ("nav.calendar", "cal.title", "cal.new", "cal.event.title", "cal.event.save"):
        assert key in src, key


def test_calendar_js_drag_sends_and_refreshes_etag():
    """Drag&drop di un evento Google: l'etag va mandato (If-Match) e riaggiornato
    dalla risposta, altrimenti il secondo drag consecutivo darebbe un 409 falso."""
    src = pathlib.Path("app/static/js/calendar_page.js").read_text(encoding="utf-8")
    assert "etag: g.etag" in src              # overlay -> extendedProps
    assert "fd.append('etag'" in src          # extendedProps -> PUT
    assert "setExtendedProp('etag'" in src    # risposta PUT -> extendedProps
