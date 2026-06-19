# tests/test_kdm_public.py
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import KdmRequestLink, KdmRequest
import secrets

client = TestClient(app)


def _make_link():
    db = SessionLocal()
    try:
        tok = secrets.token_hex(32)
        db.add(KdmRequestLink(tenant_id=1, token=tok, prefill_json={}))
        db.commit()
        return tok
    finally:
        db.close()


def test_public_form_loads():
    tok = _make_link()
    r = client.get(f"/public/kdm/{tok}")
    assert r.status_code == 200
    assert "KDM" in r.text


def test_public_form_unknown_token_404():
    r = client.get("/public/kdm/deadbeef")
    assert r.status_code == 404


def test_public_submit_creates_request(monkeypatch):
    # neutralizza notifica/email per il test
    import app.routers.kdm_public as pub
    monkeypatch.setattr(pub, "_notify_finishing", lambda db, req: None)
    tok = _make_link()
    r = client.post(f"/public/kdm/{tok}", data={
        "request_type": "kdm", "requested_title": "QUEER_FTR",
        "valid_from": "2026-09-01T20:00", "valid_to": "2026-09-30T23:00",
        "cinema_contact_email": "boxoffice@arcadia.it",
        "production_contact_name": "Mario Rossi"})
    assert r.status_code in (200, 303)
    db = SessionLocal()
    try:
        got = (db.query(KdmRequest)
               .filter(KdmRequest.requested_title == "QUEER_FTR").first())
        assert got is not None and got.status == "received"
    finally:
        db.close()
