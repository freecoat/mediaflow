import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, User, UserRole, Client, Acquisition, Contact, ContactAcquisition, EmailLink,
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
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_badge_zero_when_no_linked_contacts_have_email(client):
    c, s = client
    r = c.get("/contacts/api/notify-badge?acquisition_id=1")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


def test_badge_no_gmail_token_returns_zero_not_500(client, monkeypatch):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario", email="mario@acme.com"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.commit()
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "list_threads",
                        lambda db, uid, **kw: {"threads": [], "next_page_token": None})
    r = c.get("/contacts/api/notify-badge?acquisition_id=1")
    assert r.status_code == 200
    assert r.json() == {"count": 0}


def test_badge_counts_threads_excluding_already_linked(client, monkeypatch):
    c, s = client
    s.add(Contact(id=1, tenant_id=1, client_id=None, name="Mario", email="mario@acme.com"))
    s.commit()
    s.add(ContactAcquisition(tenant_id=1, contact_id=1, acquisition_id=1))
    s.add(EmailLink(tenant_id=1, provider="google", thread_id="TALREADY", subject="x",
                    acquisition_id=1, is_active=True))
    s.commit()
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "list_threads",
                        lambda db, uid, **kw: {"threads": [{"id": "TALREADY"}, {"id": "TNEW"}],
                                                "next_page_token": None})
    r = c.get("/contacts/api/notify-badge?acquisition_id=1")
    assert r.status_code == 200
    assert r.json() == {"count": 1}


def test_badge_unknown_acquisition_404(client):
    c, s = client
    r = c.get("/contacts/api/notify-badge?acquisition_id=999")
    assert r.status_code == 404
