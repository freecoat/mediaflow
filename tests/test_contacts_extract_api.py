import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole
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
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_extract_returns_candidates_from_thread(client, monkeypatch):
    c, s = client
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid,
        "messages": [{"from": "Mario Rossi <mario@acme.com>", "to": "a@b.com", "cc": "",
                      "body_text": "Ciao\n\nMario Rossi\nDIT\nmario@acme.com"}],
    })
    r = c.post("/contacts/api/extract", data={"thread_id": "T1"})
    assert r.status_code == 200
    cands = r.json()["candidates"]
    assert any(x["email"] == "mario@acme.com" for x in cands)


def test_extract_no_gmail_token_returns_empty_candidates(client, monkeypatch):
    c, s = client
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod.gmail, "get_thread", lambda db, uid, tid: None)
    r = c.post("/contacts/api/extract", data={"thread_id": "T1"})
    assert r.status_code == 200
    assert r.json()["candidates"] == []


def test_extract_enrich_no_provider_returns_candidate_unchanged(client, monkeypatch):
    c, s = client
    import app.routers.contacts as contacts_mod
    monkeypatch.setattr(contacts_mod, "get_provider_for_user", lambda uid, db: None)
    r = c.post("/contacts/api/extract/enrich", data={
        "name": "Mario", "email": "mario@acme.com", "signature": "Mario Rossi\nDIT\nAcme Srl"})
    assert r.status_code == 200
    b = r.json()
    assert b["name"] == "Mario"
    assert b["email"] == "mario@acme.com"
