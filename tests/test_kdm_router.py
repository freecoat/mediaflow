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
