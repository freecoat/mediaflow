"""TDD tests for KDM router (Task 9 skeleton + Task 10 CRUD endpoints).
v3.5.0-alpha.172.226
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base
from app.models import User, Role, Tenant, KdmRequest, DcpCpl
from app.models.models import UserRole
from app.services.auth import create_access_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_admin(monkeypatch):
    """TestClient autenticato come admin su DB in-memory StaticPool.

    Pattern identico a test_agent_installer.py: monkeypatch engine/SessionLocal
    di app.database + cookie access_token con permesso manage_kdm.
    """
    import app.database as database
    import app.main as main_mod
    from app.database import get_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    session = TestSession()

    tenant = Tenant(id=1, name="Tenant Test", slug="tenant-test", is_active=True)
    session.add(tenant)
    session.flush()

    admin_role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["manage_kdm", "manage_roles", "edit_planning_all"],
        is_system=True, is_active=True,
    )
    session.add(admin_role)
    session.flush()

    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin Test",
        hashed_password="x", role=UserRole.admin, role_id=admin_role.id,
        is_active=True,
    )
    session.add(admin)
    session.commit()

    def _override_get_db():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    token = create_access_token({"sub": admin.email, "tid": 1})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Task 9 skeleton tests (no auth required — unauthenticated client)
# ---------------------------------------------------------------------------

_bare_client = TestClient(__import__("app.main", fromlist=["app"]).app)


def test_kdm_page_loads():
    r = _bare_client.get("/kdm")
    # Auth middleware may redirect; accept 200 or auth redirect, never 404/500.
    assert r.status_code in (200, 302, 303, 401)


def test_requests_api_shape():
    r = _bare_client.get("/kdm/api/requests")
    assert r.status_code in (200, 401, 403)


# ---------------------------------------------------------------------------
# Task 10 tests — authenticated
# ---------------------------------------------------------------------------

def test_create_and_match_request(client_admin):
    """POST /kdm/api/requests: crea richiesta, auto-match su UUID esatto → matched."""
    session = client_admin.session
    cpl = DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:router-1",
                 source="manual", content_title_text="ROUTER_FTR")
    session.add(cpl)
    session.commit()

    r = client_admin.post("/kdm/api/requests", data={
        "request_type": "kdm",
        "requested_cpl_uuid": "urn:uuid:router-1",
        "delivery_method": "email",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] and body["status"] in ("received", "matched")
    # exact uuid → auto-linked (confidence=100 ≥ AUTO_LINK_THRESHOLD=95)
    assert body["status"] == "matched", f"expected matched, got {body['status']}"
    assert body["dcp_cpl_id"] is not None


def test_transition_legal(client_admin):
    """Legal transition received → matched persists."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req)
    session.commit()
    rid = req.id

    r = client_admin.post(f"/kdm/api/requests/{rid}/transition",
                          data={"to_status": "matched"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "matched"


def test_transition_illegal(client_admin):
    """Illegal transition (received → delivered) returns 400."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req)
    session.commit()
    rid = req.id

    r = client_admin.post(f"/kdm/api/requests/{rid}/transition",
                          data={"to_status": "delivered"})
    assert r.status_code == 400, r.text


def test_soft_delete(client_admin):
    """DELETE soft-deletes; subsequent transition returns 404."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req)
    session.commit()
    rid = req.id

    r = client_admin.delete(f"/kdm/api/requests/{rid}")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    # Subsequent operation on soft-deleted record → 404
    r2 = client_admin.post(f"/kdm/api/requests/{rid}/transition",
                           data={"to_status": "matched"})
    assert r2.status_code == 404, r2.text


# ---------------------------------------------------------------------------
# Step 1 redesign — detail view, edit, leggibili emit/confirm
# ---------------------------------------------------------------------------

def _make_linked_request(session, status="received"):
    """Crea Tenant→Client→Project→Job→DCP src + KdmRequest agganciata."""
    from app.models import Client, Project, Job, JobDeliverable, DeliverableStatus
    cli = Client(tenant_id=1, name="Cinema SRL")
    session.add(cli); session.flush()
    proj = Project(tenant_id=1, code="FILM-X", title="Film X", client_id=cli.id)
    session.add(proj); session.flush()
    job = Job(tenant_id=1, code="J-X", title="Job X", project_id=proj.id, client_id=cli.id)
    session.add(job); session.flush()
    src = JobDeliverable(tenant_id=1, job_id=job.id, name="DCP src",
                         status=DeliverableStatus.delivered)
    session.add(src); session.flush()
    req = KdmRequest(tenant_id=1, request_type="kdm", status=status,
                     job_deliverable_id=src.id, requested_title="Film X KDM")
    session.add(req); session.commit()
    return req


def test_get_request_detail(client_admin):
    """GET /kdm/api/requests/{id}: dettaglio completo con timeline eventi."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received",
                     requested_title="Detail Film", notes="hello")
    session.add(req); session.commit()

    r = client_admin.get(f"/kdm/api/requests/{req.id}")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["requested_title"] == "Detail Film"
    assert b["notes"] == "hello"
    assert "events" in b and isinstance(b["events"], list)
    assert "cinema_contact_email" in b
    assert b["has_client_cert"] is False


def test_update_request_fields(client_admin):
    """POST /kdm/api/requests/{id}: producer/operatore amplia e corregge."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received",
                     requested_title="Old")
    session.add(req); session.commit()

    r = client_admin.post(f"/kdm/api/requests/{req.id}", data={
        "requested_title": "New Title",
        "cinema_contact_email": "proj@cinema.it",
        "notes": "corretto dall'operatore",
    })
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["requested_title"] == "New Title"
    assert b["cinema_contact_email"] == "proj@cinema.it"
    assert b["notes"] == "corretto dall'operatore"


def test_update_request_sentinel_clears(client_admin):
    """Sentinel '0' svuota un campo (FormData vuoto = None non basta)."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received",
                     notes="da cancellare")
    session.add(req); session.commit()

    r = client_admin.post(f"/kdm/api/requests/{req.id}", data={"notes": "0"})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] is None


def test_emit_without_job_returns_400(client_admin):
    """Emetti su richiesta senza DCP agganciato → 400 con messaggio guida."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req); session.commit()

    r = client_admin.post(f"/kdm/api/requests/{req.id}/emit")
    assert r.status_code == 400, r.text


def test_emit_blocked_without_credentials(client_admin):
    """Emetti senza credenziali (cert/serial) → 400 anche se DCP agganciato."""
    session = client_admin.session
    req = _make_linked_request(session, status="received")
    r = client_admin.post(f"/kdm/api/requests/{req.id}/emit")
    assert r.status_code == 400, r.text
    assert "certificato" in r.text.lower() or "serial" in r.text.lower()


def test_emit_happy_path_materializes(client_admin):
    """Emetti porta a 'generated' e materializza il deliverable (con credenziale)."""
    session = client_admin.session
    req = _make_linked_request(session, status="received")
    # Step 2 gate: serve ≥1 credenziale
    rc = client_admin.post(f"/kdm/api/requests/{req.id}/certs",
                           data={"kind": "serial", "serial": "SN-001"})
    assert rc.status_code == 200, rc.text

    r = client_admin.post(f"/kdm/api/requests/{req.id}/emit")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["status"] == "generated"
    assert b["generated_at"] is not None
    assert b["job_deliverable_produced_id"] is not None


def test_confirm_delivery_reaches_confirmed(client_admin):
    """Conferma consegna porta la richiesta fino a 'confirmed'."""
    session = client_admin.session
    req = _make_linked_request(session, status="received")
    client_admin.post(f"/kdm/api/requests/{req.id}/certs",
                      data={"kind": "serial", "serial": "SN-002"})
    # emette prima
    r1 = client_admin.post(f"/kdm/api/requests/{req.id}/emit")
    assert r1.status_code == 200, r1.text

    r2 = client_admin.post(f"/kdm/api/requests/{req.id}/confirm-delivery")
    assert r2.status_code == 200, r2.text
    b = r2.json()
    assert b["status"] == "confirmed"
    assert b["confirmed_at"] is not None


# ---------------------------------------------------------------------------
# Batch — archivio, bulk, link attributi, CPL collegate
# ---------------------------------------------------------------------------

def test_active_list_excludes_completed(client_admin):
    """Lista attiva esclude le completate; archived=1 le mostra."""
    session = client_admin.session
    active = KdmRequest(tenant_id=1, request_type="kdm", status="received",
                        requested_title="ACTIVE_ONE")
    done = KdmRequest(tenant_id=1, request_type="kdm", status="confirmed",
                      requested_title="DONE_ONE")
    session.add_all([active, done]); session.commit()

    act = client_admin.get("/kdm/api/requests").json()
    titles = [r["requested_title"] for r in act]
    assert "ACTIVE_ONE" in titles and "DONE_ONE" not in titles

    arch = client_admin.get("/kdm/api/requests?archived=1").json()
    atitles = [r["requested_title"] for r in arch]
    assert "DONE_ONE" in atitles and "ACTIVE_ONE" not in atitles


def test_delete_completed_blocked(client_admin):
    """Singola delete su richiesta completata → 400."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="confirmed")
    session.add(req); session.commit()
    r = client_admin.delete(f"/kdm/api/requests/{req.id}")
    assert r.status_code == 400, r.text


def test_bulk_delete_skips_completed(client_admin):
    """bulk-delete elimina le attive, salta le completate."""
    session = client_admin.session
    a = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    b = KdmRequest(tenant_id=1, request_type="kdm", status="confirmed")
    session.add_all([a, b]); session.commit()
    fd = {"ids": f"{a.id},{b.id}"}
    r = client_admin.post("/kdm/api/requests/bulk-delete", data=fd)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 1 and body["skipped"] == 1


def test_create_link_with_attributes(client_admin):
    """Link con nome + durata → expires_at calcolata; list espone gli attributi."""
    r = client_admin.post("/kdm/api/links", data={
        "label": "Arcadia", "duration_days": "30", "prefill_title": "FILM"})
    assert r.status_code == 200, r.text
    links = client_admin.get("/kdm/api/links").json()
    lk = next(l for l in links if l["id"] == r.json()["id"])
    assert lk["label"] == "Arcadia"
    assert lk["duration_days"] == 30
    assert lk["expires_at"] is not None
    assert lk["is_expired"] is False


def test_bulk_revoke_links(client_admin):
    """bulk-revoke disattiva più link."""
    a = client_admin.post("/kdm/api/links", data={"label": "A"}).json()["id"]
    b = client_admin.post("/kdm/api/links", data={"label": "B"}).json()["id"]
    r = client_admin.post("/kdm/api/links/bulk-revoke", data={"ids": f"{a},{b}"})
    assert r.status_code == 200, r.text
    assert r.json()["revoked"] == 2
    by_id = {l["id"]: l for l in client_admin.get("/kdm/api/links").json()}
    assert a in by_id and by_id[a]["revoked"] is True
    assert b in by_id and by_id[b]["revoked"] is True


def test_cpl_linked_requests(client_admin):
    """GET /kdm/api/cpl/{id}/requests ritorna le richieste con dcp_cpl_id."""
    session = client_admin.session
    cpl = DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:link-req", source="manual",
                 content_title_text="LINKREQ")
    session.add(cpl); session.commit()
    req = KdmRequest(tenant_id=1, request_type="kdm", status="matched",
                     dcp_cpl_id=cpl.id, requested_title="REQ_ON_CPL")
    session.add(req); session.commit()

    r = client_admin.get(f"/kdm/api/cpl/{cpl.id}/requests")
    assert r.status_code == 200, r.text
    assert any(x["requested_title"] == "REQ_ON_CPL" for x in r.json())


# ---------------------------------------------------------------------------
# Step 2 — credenziali: certificati multipli + serial number
# ---------------------------------------------------------------------------

def test_add_serial_credential(client_admin):
    """POST .../certs kind=serial → 200 + appare in lista + has_credentials."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req); session.commit()

    r = client_admin.post(f"/kdm/api/requests/{req.id}/certs",
                          data={"kind": "serial", "serial": "ABC-123", "label": "Sala 1"})
    assert r.status_code == 200, r.text
    assert r.json()["serial"] == "ABC-123"

    lst = client_admin.get(f"/kdm/api/requests/{req.id}/certs")
    assert lst.status_code == 200
    assert any(c["serial"] == "ABC-123" for c in lst.json())

    detail = client_admin.get(f"/kdm/api/requests/{req.id}").json()
    assert detail["has_credentials"] is True
    assert len(detail["certificates"]) == 1


def test_add_cert_requires_pem(client_admin):
    """kind=cert senza cert_pem → 400."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req); session.commit()
    r = client_admin.post(f"/kdm/api/requests/{req.id}/certs", data={"kind": "cert"})
    assert r.status_code == 400, r.text


def test_delete_credential(client_admin):
    """DELETE .../certs/{cid} rimuove la credenziale."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req); session.commit()
    r = client_admin.post(f"/kdm/api/requests/{req.id}/certs",
                          data={"kind": "serial", "serial": "DEL-1"})
    cid = r.json()["id"]

    rd = client_admin.delete(f"/kdm/api/requests/{req.id}/certs/{cid}")
    assert rd.status_code == 200, rd.text
    lst = client_admin.get(f"/kdm/api/requests/{req.id}/certs").json()
    assert not any(c["id"] == cid for c in lst)


def test_multiple_credentials(client_admin):
    """Più credenziali (cert + serial) coesistono sulla stessa richiesta."""
    session = client_admin.session
    req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
    session.add(req); session.commit()
    client_admin.post(f"/kdm/api/requests/{req.id}/certs",
                      data={"kind": "serial", "serial": "S1"})
    client_admin.post(f"/kdm/api/requests/{req.id}/certs",
                      data={"kind": "serial", "serial": "S2"})
    lst = client_admin.get(f"/kdm/api/requests/{req.id}/certs").json()
    assert len(lst) == 2


# ---------------------------------------------------------------------------
# Task 11 tests — facility + server CRUD + cert upload
# ---------------------------------------------------------------------------

def test_facility_and_server_crud(client_admin):
    """CRUD completo CinemaFacility + CinemaServer con validazione cross-tenant."""
    # Crea facility
    r = client_admin.post("/kdm/api/facilities",
                          data={"name": "Arcadia", "kind": "cinema"})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]

    # Crea server nella facility
    r2 = client_admin.post("/kdm/api/servers",
                           data={"facility_id": fid, "manufacturer": "christie",
                                 "serial": "S-1"})
    assert r2.status_code == 200, r2.text
    sid = r2.json()["id"]

    # Lista facilities: deve contenere la nuova
    r3 = client_admin.get("/kdm/api/facilities")
    assert r3.status_code == 200, r3.text
    assert any(f["id"] == fid for f in r3.json())

    # Lista servers: deve contenere il nuovo
    r4 = client_admin.get("/kdm/api/servers")
    assert r4.status_code == 200, r4.text
    assert any(s["id"] == sid for s in r4.json())

    # Update facility
    r5 = client_admin.put(f"/kdm/api/facilities/{fid}",
                          data={"city": "Roma"})
    assert r5.status_code == 200, r5.text
    assert r5.json()["city"] == "Roma"

    # Update server
    r6 = client_admin.put(f"/kdm/api/servers/{sid}",
                          data={"model": "CP2230"})
    assert r6.status_code == 200, r6.text
    assert r6.json()["model"] == "CP2230"

    # Soft delete server
    r7 = client_admin.delete(f"/kdm/api/servers/{sid}")
    assert r7.status_code == 200, r7.text
    assert r7.json()["ok"] is True

    # Server non più in lista
    r8 = client_admin.get("/kdm/api/servers")
    assert not any(s["id"] == sid for s in r8.json())

    # Soft delete facility
    r9 = client_admin.delete(f"/kdm/api/facilities/{fid}")
    assert r9.status_code == 200, r9.text
    assert r9.json()["ok"] is True

    # Facility non più in lista
    r10 = client_admin.get("/kdm/api/facilities")
    assert not any(f["id"] == fid for f in r10.json())


def test_server_cross_tenant_facility_rejected(client_admin):
    """Creare server con facility_id di altro tenant → 404."""
    # Facility_id=9999 non esiste nel tenant corrente → deve dare 404
    r = client_admin.post("/kdm/api/servers",
                          data={"facility_id": 9999, "manufacturer": "barco",
                                "serial": "X-1"})
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Task 12 tests — CPL list/parse/manual/scan endpoints
# ---------------------------------------------------------------------------

def test_cpl_parse_endpoint(client_admin):
    """POST /kdm/api/cpl/parse: upload CPL fixture → 200 + cpl_uuid starts 'urn:uuid:'."""
    from pathlib import Path
    xml = (Path(__file__).parent / "fixtures" / "cpl_smpte.xml").read_bytes()
    r = client_admin.post("/kdm/api/cpl/parse",
                          files={"file": ("cpl.xml", xml, "application/xml")})
    assert r.status_code == 200, r.text
    assert r.json()["cpl_uuid"].startswith("urn:uuid:")


def test_cpl_parse_bad_xml_returns_400(client_admin):
    """POST /kdm/api/cpl/parse: XML malformato → 400."""
    garbage = b"not xml at all <<<>>>"
    r = client_admin.post("/kdm/api/cpl/parse",
                          files={"file": ("bad.xml", garbage, "application/xml")})
    assert r.status_code == 400, r.text


def test_cpl_list(client_admin):
    """GET /kdm/api/cpl: ritorna lista CPL attive tenant-scoped."""
    session = client_admin.session
    cpl = DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:list-test-1",
                 source="manual", content_title_text="LIST_TEST")
    session.add(cpl)
    session.commit()

    r = client_admin.get("/kdm/api/cpl")
    assert r.status_code == 200, r.text
    ids = [c["cpl_uuid"] for c in r.json()]
    assert "urn:uuid:list-test-1" in ids


def test_cpl_manual(client_admin):
    """POST /kdm/api/cpl/manual: crea CPL manuale → 200 con source='manual'."""
    r = client_admin.post("/kdm/api/cpl/manual", data={
        "cpl_uuid": "urn:uuid:manual-test-1",
        "content_title_text": "MANUAL_TITLE",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cpl_uuid"] == "urn:uuid:manual-test-1"
    assert body["source"] == "manual"


def test_cpl_scan_stub(client_admin):
    """POST /kdm/api/cpl/scan: stub → 501 con ok=False."""
    r = client_admin.post("/kdm/api/cpl/scan")
    assert r.status_code == 501, r.text
    assert r.json()["ok"] is False


# ---------------------------------------------------------------------------
# Task 17 tests — public request-link generation (operator side)
# ---------------------------------------------------------------------------

def test_create_public_link(client_admin):
    """POST /kdm/api/links: crea link pubblico con prefill → {id, token, url}."""
    r = client_admin.post("/kdm/api/links", data={
        "request_type": "kdm", "prefill_title": "QUEER_FTR"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["token"] and "/public/kdm/" in b["url"]


def test_list_public_links(client_admin):
    """GET /kdm/api/links: ritorna lista link attivi tenant-scoped."""
    # Crea un link prima
    r1 = client_admin.post("/kdm/api/links", data={"prefill_title": "FILM_A"})
    assert r1.status_code == 200, r1.text
    link_id = r1.json()["id"]

    r2 = client_admin.get("/kdm/api/links")
    assert r2.status_code == 200, r2.text
    ids = [l["id"] for l in r2.json()]
    assert link_id in ids


def test_revoke_public_link(client_admin):
    """POST /kdm/api/links/{id}/revoke: is_active → False, non appare più in lista."""
    r1 = client_admin.post("/kdm/api/links", data={"prefill_title": "FILM_B"})
    assert r1.status_code == 200, r1.text
    link_id = r1.json()["id"]

    r2 = client_admin.post(f"/kdm/api/links/{link_id}/revoke")
    assert r2.status_code == 200, r2.text
    assert r2.json()["ok"] is True

    # Deve ancora apparire nella lista ma con revoked=True (nuovo contratto)
    r3 = client_admin.get("/kdm/api/links")
    assert r3.status_code == 200, r3.text
    by_id = {l["id"]: l for l in r3.json()}
    assert link_id in by_id
    assert by_id[link_id]["revoked"] is True


def test_revoke_nonexistent_link(client_admin):
    """POST /kdm/api/links/9999/revoke: link inesistente → 404."""
    r = client_admin.post("/kdm/api/links/9999/revoke")
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Task 13 tests — /kdm page UI
# ---------------------------------------------------------------------------

def test_kdm_page_html_authenticated(client_admin):
    """GET /kdm con client autenticato → 200 e HTML con i 3 tab + script kdm.js."""
    r = client_admin.get("/kdm")
    assert r.status_code == 200, r.text
    html = r.text
    # 3 tab markers
    assert 'data-tab="requests"' in html, "tab requests mancante"
    assert 'data-tab="facilities"' in html, "tab facilities mancante"
    assert 'data-tab="cpl"' in html, "tab cpl mancante"
    # script kdm.js caricato
    assert '/static/js/kdm.js' in html, "script kdm.js mancante"


def test_kdm_page_contains_tab_panes(client_admin):
    """GET /kdm: HTML contiene i pane delle 3 tab con id attesi."""
    r = client_admin.get("/kdm")
    assert r.status_code == 200, r.text
    html = r.text
    assert 'id="kdm-tab-requests"' in html
    assert 'id="kdm-tab-facilities"' in html
    assert 'id="kdm-tab-cpl"' in html


def test_kdm_page_has_step1_redesign_elements(client_admin):
    """GET /kdm: render contiene filtri + modal dettaglio + azioni leggibili."""
    r = client_admin.get("/kdm")
    assert r.status_code == 200, r.text
    html = r.text
    assert 'id="kdm-filters"' in html, "host filtri mancante"
    assert 'id="kdm-modal-detail"' in html, "modal dettaglio mancante"
    assert 'data-i18n="kdm.btn.emit"' in html, "bottone Emetti mancante"
    assert 'data-i18n="kdm.btn.confirm_delivery"' in html, "bottone Conferma mancante"
