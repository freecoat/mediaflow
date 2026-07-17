"""Endpoint scrittura eventi Google esterni + diagnosticabilità overlay (α.172.253).

Design 2026-07-15 Domanda 6: l'overlay resta best-effort (sempre 200, mai eccezione
al chiamante) ma un fallimento va distinto dal "non connesso" — il bare except che
inghiottiva tutto rendeva i due casi indistinguibili.
"""
from datetime import timedelta

import urllib.error

from tests.test_calendar_api import client  # noqa: F401
from app.models.models import UserOAuthToken
from app.services.clock import now_utc


def _connect(s, scopes="https://www.googleapis.com/auth/calendar.events"):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         expires_at=now_utc() + timedelta(hours=1), scopes=scopes))
    s.commit()


def _boom(status):
    def _fn(*a, **k):
        raise urllib.error.HTTPError("url", status, "err", {}, None)
    return _fn


def test_get_google_event_ok(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {
            "id": "e1", "summary": "Riunione", "etag": '"abc"',
            "start": {"dateTime": "2026-07-10T09:00:00Z"},
            "end": {"dateTime": "2026-07-10T10:00:00Z"}})
    r = c.get("/calendar/api/google-events/cal1/e1")
    assert r.status_code == 200
    assert r.json()["title"] == "Riunione"
    assert r.json()["etag"] == '"abc"'


def test_get_google_event_404_without_connection(client):
    c, s = client
    assert c.get("/calendar/api/google-events/cal1/e1").status_code == 404


def test_put_google_event_updates(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {
            "id": "e1", "summary": body.get("summary")})
    r = c.put("/calendar/api/google-events/cal1/e1", data={
        "title": "Rinviata", "start_at": "2026-07-10T09:00:00", "end_at": "2026-07-10T10:00:00"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_put_google_event_invia_attendees_e_description(client, monkeypatch):
    """Campi portati dal ramo mobile-responsive-email: devono arrivare a Google
    passando dall'endpoint etag-protetto."""
    c, s = client
    _connect(s)
    seen = {}
    from app.services import google_calendar as gc

    def fake(m, u, t, body=None, params=None, extra_headers=None):
        seen["body"] = body; seen["params"] = params
        return {"id": "e1"}

    monkeypatch.setattr(gc, "_google_request", fake)
    r = c.put("/calendar/api/google-events/cal1/e1", data={
        "title": "Riunione", "description": "note",
        "attendees": "a@x.it, b@x.it", "location": "Sala 1"})
    assert r.status_code == 200, r.text
    assert seen["body"]["attendees"] == [{"email": "a@x.it"}, {"email": "b@x.it"}]
    assert seen["body"]["description"] == "note"
    assert seen["body"]["location"] == "Sala 1"
    assert seen["params"] == {"sendUpdates": "all"}


def test_put_google_event_full_edit_svuota_i_campi(client, monkeypatch):
    """Trappola multipart: una stringa vuota arriva a FastAPI come None, identica
    a un campo non inviato. Col marker `full_edit` il modale dichiara di possedere
    quei campi, quindi il vuoto è voluto e deve svuotarli davvero."""
    c, s = client
    _connect(s)
    seen = {}
    from app.services import google_calendar as gc

    def fake(m, u, t, body=None, params=None, extra_headers=None):
        seen["body"] = body
        return {"id": "e1"}

    monkeypatch.setattr(gc, "_google_request", fake)
    r = c.put("/calendar/api/google-events/cal1/e1",
              data={"title": "X", "attendees": "", "description": "", "full_edit": "1"})
    assert r.status_code == 200, r.text
    assert seen["body"]["attendees"] == [], "lista svuotata, non lasciata intatta"
    assert seen["body"]["description"] == "", "descrizione svuotata, non lasciata intatta"


def test_put_google_event_senza_full_edit_il_vuoto_non_tocca_nulla(client, monkeypatch):
    """Il drag&drop non manda full_edit: deve toccare solo le date, mai azzerare
    partecipanti o descrizione dell'evento trascinato."""
    c, s = client
    _connect(s)
    seen = {}
    from app.services import google_calendar as gc

    def fake(m, u, t, body=None, params=None, extra_headers=None):
        seen["body"] = body
        return {"id": "e1"}

    monkeypatch.setattr(gc, "_google_request", fake)
    r = c.put("/calendar/api/google-events/cal1/e1", data={
        "start_at": "2026-07-10T09:00:00", "end_at": "2026-07-10T10:00:00",
        "etag": '"abc"'})
    assert r.status_code == 200, r.text
    assert "attendees" not in seen["body"]
    assert "description" not in seen["body"]
    assert "location" not in seen["body"]


def test_put_google_event_campi_non_inviati_non_finiscono_nel_body(client, monkeypatch):
    """PATCH parziale: ciò che il modale non manda non deve essere toccato su
    Google (altrimenti si azzerano i campi che Claqo non modella)."""
    c, s = client
    _connect(s)
    seen = {}
    from app.services import google_calendar as gc

    def fake(m, u, t, body=None, params=None, extra_headers=None):
        seen["body"] = body
        return {"id": "e1"}

    monkeypatch.setattr(gc, "_google_request", fake)
    r = c.put("/calendar/api/google-events/cal1/e1", data={"title": "Solo titolo"})
    assert r.status_code == 200, r.text
    assert "attendees" not in seen["body"]
    assert "description" not in seen["body"]
    assert "location" not in seen["body"]


def test_put_google_event_conflict_returns_409(client, monkeypatch):
    """412 di Google -> 409 al client: l'evento e' cambiato, non sovrascrivere."""
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request", _boom(412))
    r = c.put("/calendar/api/google-events/cal1/e1", data={"title": "X", "etag": '"stale"'})
    assert r.status_code == 409


def test_put_google_event_forbidden_returns_403(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request", _boom(403))
    r = c.put("/calendar/api/google-events/cal1/e1", data={"title": "X"})
    assert r.status_code == 403


def test_delete_google_event_ok(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request",
        lambda m, u, t, body=None, params=None, extra_headers=None: {})
    r = c.request("DELETE", "/calendar/api/google-events/cal1/e1")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_delete_google_event_404_when_already_gone_is_ok(client, monkeypatch):
    c, s = client
    _connect(s)
    from app.services import google_calendar as gc
    monkeypatch.setattr(gc, "_google_request", _boom(404))
    r = c.request("DELETE", "/calendar/api/google-events/cal1/e1")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_google_write_routes_registered(client):
    import app.main as main_mod
    paths = {r.path for r in main_mod.app.routes if hasattr(r, "path")}
    assert "/calendar/api/google-events/{calendar_id}/{event_id}" in paths


def test_overlay_flags_error_on_exception(client, monkeypatch):
    """Fallimento reale != non connesso: l'overlay resta 200 ma lo dichiara."""
    c, s = client
    _connect(s)
    import app.routers.calendar as calmod

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(calmod.google_calendar, "list_google_events", boom)
    r = c.get("/calendar/api/google-overlay",
              params={"start": "2026-07-01T00:00:00Z", "end": "2026-07-31T00:00:00Z"})
    assert r.status_code == 200
    assert r.json() == {"events": [], "error": True}


def test_overlay_no_error_flag_when_not_connected(client):
    """Non connesso non e' un errore: contratto invariato."""
    c, s = client
    r = c.get("/calendar/api/google-overlay",
              params={"start": "2026-07-01T00:00:00Z", "end": "2026-07-31T00:00:00Z"})
    assert r.status_code == 200
    assert r.json() == {"events": []}
