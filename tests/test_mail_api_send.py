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


def test_send_ok(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    captured = {}
    def fake_send(db, uid, **k):
        captured.update(k); return {"id": "SENT1", "threadId": "T1"}
    monkeypatch.setattr(mailmod.gmail, "send_message", fake_send)
    r = c.post("/mail/api/send", data={"to": "x@y.com", "subject": "S", "body": "<p>b</p>",
                                       "thread_id": "T1", "in_reply_to": "<a@m>"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert captured["to"] == "x@y.com"
    assert captured["thread_id"] == "T1"
    assert captured["in_reply_to"] == "<a@m>"


def test_send_failure_returns_ok_false(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "send_message", lambda db, uid, **k: None)
    r = c.post("/mail/api/send", data={"to": "x@y.com", "subject": "S", "body": "b"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_send_with_attachment(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    captured = {}
    def fake_send(db, uid, **k):
        captured.update(k); return {"id": "S2"}
    monkeypatch.setattr(mailmod.gmail, "send_message", fake_send)
    r = c.post("/mail/api/send", data={"to": "x@y.com", "subject": "S", "body": "b"},
               files={"attachments": ("n.txt", b"hello", "text/plain")})
    assert r.status_code == 200
    assert captured["attachments"][0]["filename"] == "n.txt"
    assert captured["attachments"][0]["data"] == b"hello"


def test_draft_create(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "save_draft", lambda db, uid, **k: {"id": "D1"})
    r = c.post("/mail/api/draft", data={"to": "x@y.com", "subject": "S", "body": "b"})
    assert r.status_code == 200
    assert r.json()["id"] == "D1"


def test_draft_delete(client, monkeypatch):
    c, s = client
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "delete_draft", lambda db, uid, did: True)
    r = c.delete("/mail/api/draft/D1")
    assert r.json()["ok"] is True
