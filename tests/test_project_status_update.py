# tests/test_project_status_update.py
# Regression test: PUT /projects/api/{id} persists status change.
# Backend path confirmed: app/routers/projects.py @router.put("/api/{project_id}")
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Project, ProjectStatus
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
                permissions=["view_projects", "edit_projects"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="TestClient")); s.flush()
    s.add(Project(id=1, tenant_id=1, code="P1", title="Test Project", client_id=1,
                  status=ProjectStatus.prospect)); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_project_status_update_persists(client):
    """PUT /projects/api/{id} with status=active must persist the change."""
    c, s = client
    r = c.put("/projects/api/1", data={"status": "active"})
    assert r.status_code in (200, 201), r.text
    s.expire_all()
    proj = s.query(Project).filter_by(id=1).first()
    assert proj.status == ProjectStatus.active


def test_project_status_all_enum_values(client):
    """Every ProjectStatus value must round-trip through PUT."""
    c, s = client
    for val in ("quoting", "active", "completed", "archived", "prospect"):
        r = c.put("/projects/api/1", data={"status": val})
        assert r.status_code in (200, 201), f"status={val}: {r.text}"
        s.expire_all()
        proj = s.query(Project).filter_by(id=1).first()
        assert proj.status.value == val, f"Expected {val}, got {proj.status.value}"
