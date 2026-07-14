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


def test_detail_includes_client_acquisitions_projects_activities_emails(client):
    import datetime
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=1, name="Mario Rossi"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1, role="referente"))
    s.add(ContactProject(tenant_id=1, contact_id=1, project_id=1, role="DIT"))
    s.add(Activity(tenant_id=1, contact_id=1, subject="Chiamata",
                   occurred_at=datetime.datetime(2026, 7, 1)))
    s.add(EmailLink(tenant_id=1, provider="google", thread_id="T1", subject="Oggetto",
                    acquisition_id=1, is_active=True))
    s.commit()
    r = c.get("/contacts/api/1")
    assert r.status_code == 200
    b = r.json()
    assert b["client"] == {"id": 1, "name": "Cliente A"}
    assert b["acquisitions"] == [{"id": 1, "title": "Trattativa", "role": "referente"}]
    assert b["projects"] == [{"id": 1, "code": "P1", "title": "Progetto", "role": "DIT"}]
    assert len(b["activities"]) == 1
    assert len(b["email_links"]) == 1
    assert b["email_links"][0]["thread_id"] == "T1"


def test_detail_404_cross_tenant(client):
    c, s = client
    s.add(Tenant(id=2, name="T2", slug="t2", is_active=True))
    s.add(Contact(id=1, tenant_id=2, client_id=None, name="Altro tenant"))
    s.commit()
    r = c.get("/contacts/api/1")
    assert r.status_code == 404


def test_create_standalone_orphan(client):
    c, s = client
    r = c.post("/contacts/api/create", data={
        "name": "Nuovo Contatto", "company_text": "ACME Srl", "email": "n@acme.com"})
    assert r.status_code == 200
    b = r.json()
    assert b["client_id"] is None
    assert b["company_text"] == "ACME Srl"
    assert b["source"] == "manual"


def test_create_dedups_by_email_returns_existing(client):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario Rossi", email="mario@acme.com"))
    s.commit()
    r = c.post("/contacts/api/create", data={"name": "Mario R.", "email": "Mario@ACME.com"})
    assert r.status_code == 200
    b = r.json()
    assert b["existing_id"] == 1
    assert s.query(Contact).count() == 1


def test_create_with_unknown_client_id_404(client):
    c, s = client
    r = c.post("/contacts/api/create", data={"name": "X", "client_id": "999"})
    assert r.status_code == 404
