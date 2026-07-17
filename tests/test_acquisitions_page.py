# tests/test_acquisitions_page.py
"""Smoke test: GET /acquisitions page returns 200 and expected HTML markers."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole
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
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_acquisitions_page_loads(client):
    """GET /acquisitions returns 200 with expected HTML markers."""
    c, _ = client
    r = c.get("/acquisitions")
    assert r.status_code == 200, r.text
    html = r.text
    # Must contain the kanban board container
    assert "acq-kanban-board" in html
    # Must contain the table container
    assert "acq-table" in html
    # Must contain the detail panel
    assert "acq-detail-panel" in html
    # Must contain the agenda section
    assert "acq-agenda-list" in html
    # Must have the new button
    assert "acq-btn-new" in html


def test_acquisitions_has_mobile_media_query():
    import pathlib
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert "max-width: 768px" in html
    assert "position: fixed" in html


def test_acquisitions_tabs_scrollable_mobile():
    import pathlib
    html = pathlib.Path("app/templates/pages/acquisitions.html").read_text(encoding="utf-8")
    assert "overflow-x" in html
