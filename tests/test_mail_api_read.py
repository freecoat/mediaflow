import pytest
from fastapi.testclient import TestClient
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    # Vedi test_documents_api.py: il middleware auth_guard risolve l'utente da un
    # JWT cookie reale via app.database.SessionLocal() PRIMA del router → serve
    # cookie reale + puntare engine/SessionLocal al DB di test.
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


def test_status_disconnected(client):
    c, s = client
    r = c.get("/mail/api/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_status_connected(client):
    c, s = client
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         account_email="admin@gmail.com",
                         scopes="https://www.googleapis.com/auth/gmail.readonly",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()
    r = c.get("/mail/api/status")
    b = r.json()
    assert b["connected"] is True
    assert b["account_email"] == "admin@gmail.com"


def test_threads(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "list_threads",
                        lambda db, uid, **k: {"threads": [{"id": "T1", "snippet": "x"}], "next_page_token": None})
    r = c.get("/mail/api/threads", params={"label": "INBOX"})
    assert r.status_code == 200
    assert r.json()["threads"][0]["id"] == "T1"


def test_thread_404(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "get_thread", lambda db, uid, tid: None)
    assert c.get("/mail/api/thread/NOPE").status_code == 404


def test_thread_ok(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "get_thread",
                        lambda db, uid, tid: {"id": tid, "messages": [{"id": "M1", "subject": "S"}]})
    r = c.get("/mail/api/thread/T1")
    assert r.json()["messages"][0]["subject"] == "S"


def test_labels(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "list_labels",
                        lambda db, uid: [{"id": "INBOX", "name": "INBOX", "type": "system"}])
    r = c.get("/mail/api/labels")
    assert r.json()["labels"][0]["id"] == "INBOX"


def test_attachment_download(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "get_attachment", lambda db, uid, mid, aid: b"filebytes")
    r = c.get("/mail/api/attachment/M1/ATT1", params={"filename": "a.txt", "mime": "text/plain"})
    assert r.status_code == 200
    assert r.content == b"filebytes"
    assert "attachment" in r.headers.get("content-disposition", "")
