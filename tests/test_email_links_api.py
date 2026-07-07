import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (Base, Tenant, User, UserRole, Client, Acquisition, Activity)
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
    s.add(Acquisition(id=1, tenant_id=1, title="Trattativa", prospect_name="Trattativa", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_pin_by_thread_id_creates_link_and_activity(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid, "messages": [{"id": "M1", "from": "m@x.com", "subject": "Oggetto",
                                 "snippet": "ciao", "date": "Mon, 7 Jul 2026"}]})
    r = c.post("/acquisitions/api/1/emails/link", data={"thread_id": "T1"})
    assert r.status_code == 200
    b = r.json()
    assert b["thread_id"] == "T1"
    assert b["subject"] == "Oggetto"
    acts = s.query(Activity).filter(Activity.acquisition_id == 1).all()
    assert len(acts) == 1
    assert acts[0].type.value == "email"


def test_pin_by_url(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "parse_gmail_thread_id", lambda u: "TZ")
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: None)
    r = c.post("/acquisitions/api/1/emails/link",
               data={"url": "https://mail.google.com/mail/u/0/#inbox/TZ"})
    assert r.status_code == 200
    assert r.json()["thread_id"] == "TZ"
    assert r.json()["subject"]


def test_pin_non_gmail_url_400(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "parse_gmail_thread_id", lambda u: None)
    r = c.post("/acquisitions/api/1/emails/link", data={"url": "https://example.com/x"})
    assert r.status_code == 400


def test_list_filtered(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid, "messages": [{"from": "a@b.com", "subject": "S", "snippet": "x", "date": "d"}]})
    c.post("/acquisitions/api/1/emails/link", data={"thread_id": "T1"})
    r = c.get("/acquisitions/api/1/emails")
    assert r.status_code == 200
    assert len(r.json()["emails"]) == 1


def test_delete_soft(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: {
        "id": tid, "messages": [{"from": "a@b.com", "subject": "S", "snippet": "x", "date": "d"}]})
    lid = c.post("/acquisitions/api/1/emails/link", data={"thread_id": "T2"}).json()["id"]
    assert c.delete(f"/email-links/{lid}").json()["ok"] is True
    r = c.get("/acquisitions/api/1/emails")
    assert all(e["id"] != lid for e in r.json()["emails"])


def test_acquisition_404(client, monkeypatch):
    c, s = client
    import app.routers.email_links as em
    monkeypatch.setattr(em.gmail, "get_thread", lambda db, uid, tid: None)
    r = c.post("/acquisitions/api/999/emails/link", data={"thread_id": "T1"})
    assert r.status_code == 404
