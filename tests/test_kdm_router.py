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
