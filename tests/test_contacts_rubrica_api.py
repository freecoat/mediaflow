import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, User, UserRole, Client, Acquisition, Project, Contact,
    ContactAcquisition, ContactProject, Activity, EmailLink,
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
    s.add(Client(id=1, tenant_id=1, name="Cliente A"))
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_list_returns_all_active_contacts_with_link_counts(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Mario Rossi"))
    s.add(Contact(id=2, tenant_id=1, client_id=None, name="Orfano", company_text="ACME"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.commit()
    r = c.get("/contacts/api/list")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    m = next(i for i in items if i["id"] == 1)
    assert m["links"] == {"acquisitions": 1, "projects": 0}


def test_list_search_filters_by_name_email_company(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario Rossi", email="mario@acme.com"))
    s.add(Contact(id=2, tenant_id=1, client_id=None, name="Anna Bianchi", company_text="Studio X"))
    s.commit()
    r = c.get("/contacts/api/list?search=acme")
    assert [i["id"] for i in r.json()["items"]] == [1]
    r2 = c.get("/contacts/api/list?search=studio")
    assert [i["id"] for i in r2.json()["items"]] == [2]


def test_list_triage_returns_only_orphans(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Con cliente"))
    s.add(Contact(id=2, tenant_id=1, client_id=None, name="Orfano puro"))
    s.add(Contact(id=3, tenant_id=1, client_id=None, name="Orfano ma linkato"))
    s.commit()
    s.add(ContactProject(tenant_id=1, contact_id=3, project_id=1))
    s.commit()
    r = c.get("/contacts/api/list?triage=1")
    assert [i["id"] for i in r.json()["items"]] == [2]


def test_match_by_email_case_insensitive(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario Rossi", email="Mario@Acme.com"))
    s.commit()
    r = c.get("/contacts/api/match?email=mario@acme.com")
    assert r.json()["id"] == 1
    r2 = c.get("/contacts/api/match?email=nope@x.com")
    assert r2.json()["id"] is None
