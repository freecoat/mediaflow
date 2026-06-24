# tests/test_kdm_public.py
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import KdmRequestLink, KdmRequest, KdmRequestCertificate, Project, Client
import secrets

client = TestClient(app)


def _make_link(project_id=None):
    db = SessionLocal()
    try:
        tok = secrets.token_hex(32)
        db.add(KdmRequestLink(tenant_id=1, token=tok, prefill_json={},
                              project_id=project_id))
        db.commit()
        return tok
    finally:
        db.close()


def _make_project():
    db = SessionLocal()
    try:
        # Ensure a client exists to satisfy the NOT NULL FK
        client = db.query(Client).filter(Client.tenant_id == 1).first()
        if client is None:
            client = Client(tenant_id=1, name="Test Client (kdm tests)",
                            contact_email="kdmtest@mediaflow.it")
            db.add(client)
            db.flush()
        p = Project(tenant_id=1, title="Test Project Banner",
                    code=f"TST-{secrets.token_hex(4)}", client_id=client.id)
        db.add(p)
        db.commit()
        db.refresh(p)
        return p.id
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


def test_public_form_expired_link_410():
    """Link con expires_at nel passato → 410 Gone."""
    from datetime import timedelta
    from app.services.clock import now_utc
    db = SessionLocal()
    try:
        tok = secrets.token_hex(32)
        db.add(KdmRequestLink(tenant_id=1, token=tok, prefill_json={},
                              expires_at=now_utc() - timedelta(days=1)))
        db.commit()
    finally:
        db.close()
    r = client.get(f"/public/kdm/{tok}")
    assert r.status_code == 410, r.text


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


def test_public_submit_creates_serial_credentials(monkeypatch):
    """Step 2: serials nel form pubblico → righe KdmRequestCertificate kind=serial."""
    import app.routers.kdm_public as pub
    monkeypatch.setattr(pub, "_notify_finishing", lambda db, req: None)
    tok = _make_link()
    title = f"CRED_TEST_{secrets.token_hex(6)}"
    r = client.post(f"/public/kdm/{tok}", data={
        "request_type": "kdm", "requested_title": title,
        "cinema_contact_email": "x@y.it",
        "serials": "SN-AAA\nSN-BBB\n\nSN-CCC"})
    assert r.status_code in (200, 303)
    db = SessionLocal()
    try:
        got = db.query(KdmRequest).filter(KdmRequest.requested_title == title).first()
        assert got is not None
        certs = (db.query(KdmRequestCertificate)
                 .filter(KdmRequestCertificate.kdm_request_id == got.id).all())
        serials = sorted(c.serial for c in certs)
        assert serials == ["SN-AAA", "SN-BBB", "SN-CCC"], serials
        assert all(c.kind == "serial" for c in certs)
    finally:
        db.close()


def test_bogus_request_type_normalized_to_kdm(monkeypatch):
    """I2: request_type not in ('kdm','dkdm') must be silently normalised to 'kdm'."""
    import app.routers.kdm_public as pub
    monkeypatch.setattr(pub, "_notify_finishing", lambda db, req: None)
    tok = _make_link()
    unique_title = f"BOGUS_TYPE_{secrets.token_hex(6)}"
    r = client.post(f"/public/kdm/{tok}", data={
        "request_type": "injection_attempt",
        "requested_title": unique_title,
        "cinema_contact_email": "test@example.com"})
    assert r.status_code in (200, 303)
    db = SessionLocal()
    try:
        got = (db.query(KdmRequest)
               .filter(KdmRequest.requested_title == unique_title).first())
        assert got is not None, "KdmRequest not found in DB"
        assert got.request_type == "kdm", (
            f"Expected 'kdm', got {got.request_type!r}")
    finally:
        db.close()


def test_submit_success_preserves_project_banner(monkeypatch):
    """I1: success render must include project title when link has project_id."""
    import app.routers.kdm_public as pub
    monkeypatch.setattr(pub, "_notify_finishing", lambda db, req: None)
    project_id = _make_project()
    tok = _make_link(project_id=project_id)
    unique_title = f"BANNER_TEST_{secrets.token_hex(6)}"
    r = client.post(f"/public/kdm/{tok}", data={
        "request_type": "kdm",
        "requested_title": unique_title,
        "cinema_contact_email": "test@example.com"})
    assert r.status_code in (200, 303)
    assert "Test Project Banner" in r.text, (
        "Project title missing from success response")
