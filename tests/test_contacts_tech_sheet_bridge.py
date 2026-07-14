import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, User, UserRole, Client, Project, ProjectTechSheet, Contact, ContactProject,
)
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
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.add(ProjectTechSheet(id=1, tenant_id=1, project_id=1, data={
        "contacts": [{"role": "DIT", "resource_id": None, "name_text": "Mario Rossi",
                      "email": "mario@acme.com", "phone": "123"}],
    }))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_from_tech_sheet_creates_contact_links_project_and_writes_back_id(client):
    c, s = client
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "1", "idx": "0", "name": "Mario Rossi",
        "email": "mario@acme.com", "phone": "123", "role": "DIT"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing"] is False
    cid = b["id"]
    assert s.query(ContactProject).filter_by(contact_id=cid, project_id=1).count() == 1
    ts = s.query(ProjectTechSheet).filter_by(project_id=1).first()
    assert ts.data["contacts"][0]["contact_id"] == cid


def test_from_tech_sheet_dedups_by_email_reuses_existing_contact(client):
    c, s = client
    s.add(Contact(id=5, tenant_id=1, client_id=None, name="Mario Rossi", email="mario@acme.com"))
    s.commit()
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "1", "idx": "0", "name": "Mario Rossi", "email": "mario@acme.com"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing"] is True
    assert b["id"] == 5
    assert s.query(Contact).count() == 1


def test_from_tech_sheet_invalid_idx_400(client):
    c, s = client
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "1", "idx": "9", "name": "X"})
    assert r.status_code == 400


def test_from_tech_sheet_unknown_project_404(client):
    c, s = client
    r = c.post("/contacts/api/from-tech-sheet", data={
        "project_id": "999", "idx": "0", "name": "X"})
    assert r.status_code == 404
