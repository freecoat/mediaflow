import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    # Stesso pattern di test_mail_api_read: JWT cookie reale + engine/SessionLocal
    # puntati al DB di test (auth_guard risolve l'utente PRIMA del router).
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


def test_signature_empty_by_default(client):
    c, s = client
    r = c.get("/mail/api/signature")
    assert r.status_code == 200
    assert r.json()["signature"] == ""


def test_signature_save_and_read(client):
    c, s = client
    html = "<p>Matteo Lepore<br><b>Post</b></p>"
    r = c.post("/mail/api/signature", data={"signature": html})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert c.get("/mail/api/signature").json()["signature"] == html


def test_signature_clear(client):
    c, s = client
    c.post("/mail/api/signature", data={"signature": "<p>x</p>"})
    c.post("/mail/api/signature", data={"signature": ""})
    assert c.get("/mail/api/signature").json()["signature"] == ""
    assert s.get(User, 1).email_signature is None
