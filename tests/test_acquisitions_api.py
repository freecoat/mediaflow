# tests/test_acquisitions_api.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Department
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    # Patch engine + SessionLocal so auth middleware uses the test DB
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="manager", name="Mgr",
                permissions=["view_acquisitions", "manage_acquisitions"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Lucky")); s.flush()
    s.add(Department(id=1, tenant_id=1, name="DI", code="DI", sort_order=1)); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_create_list_get_acquisition(client):
    c, s = client
    r = c.post("/acquisitions/api", data={
        "title": "Film X", "client_id": "1", "stage": "lead",
        "estimated_value": "80000", "department_ids": "1"})
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    lst = c.get("/acquisitions/api/list").json()
    assert any(a["id"] == aid for a in lst["items"])
    det = c.get(f"/acquisitions/api/{aid}").json()
    assert det["title"] == "Film X"
    assert det["weighted_value"] == "8000.00"  # 80000*10%
    assert det["departments"][0]["name"] == "DI"


def test_summary_and_agenda(client):
    c, _ = client
    c.post("/acquisitions/api", data={"title": "A", "client_id": "1",
           "stage": "negotiation", "estimated_value": "100000"})
    summ = c.get("/acquisitions/api/summary").json()
    assert summ["open_count"] == 1
    assert summ["total_weighted"] == "70000.00"
    ag = c.get("/acquisitions/api/agenda").json()
    assert "items" in ag


def test_delete_soft(client):
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "Z", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    assert c.delete(f"/acquisitions/api/{aid}").status_code == 200
    lst = c.get("/acquisitions/api/list").json()
    assert all(a["id"] != aid for a in lst["items"])


def test_soft_deleted_returns_404(client):
    """GET /acquisitions/api/{id} must 404 after soft-delete (is_active=False)."""
    c, _ = client
    aid = c.post("/acquisitions/api", data={"title": "ToDelete", "client_id": "1",
                 "stage": "lead", "estimated_value": "0"}).json()["id"]
    assert c.delete(f"/acquisitions/api/{aid}").status_code == 200
    r = c.get(f"/acquisitions/api/{aid}")
    assert r.status_code == 404, f"Expected 404 for soft-deleted record, got {r.status_code}"
