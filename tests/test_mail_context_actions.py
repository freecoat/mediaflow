"""Gate scope pieno per elimina-definitivo/svuota-cestino (α.172.263)."""
import pytest
from datetime import timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
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


def _connect(s, scopes):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         scopes=scopes, expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def test_status_mail_full_false_without_scope(client):
    c, s = client
    _connect(s, "https://www.googleapis.com/auth/gmail.modify")
    r = c.get("/mail/api/status")
    assert r.status_code == 200
    assert r.json()["mail_full"] is False


def test_status_mail_full_true_with_scope(client):
    c, s = client
    _connect(s, "https://www.googleapis.com/auth/gmail.modify https://mail.google.com/")
    r = c.get("/mail/api/status")
    assert r.json()["mail_full"] is True


def test_delete_forever_403_without_scope(client):
    c, s = client
    _connect(s, "https://www.googleapis.com/auth/gmail.modify")
    r = c.post("/mail/api/threads/action",
               data={"thread_ids": "T1", "action": "delete_forever"})
    assert r.status_code == 403


def test_delete_forever_ok_with_scope(client, monkeypatch):
    c, s = client
    _connect(s, "https://mail.google.com/")
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "delete_thread_forever", lambda db, uid, tid: True)
    r = c.post("/mail/api/threads/action",
               data={"thread_ids": "T1,T2", "action": "delete_forever"})
    assert r.status_code == 200
    assert r.json() == {"ok": 2, "failed": 0}


def test_empty_trash_403_without_scope(client):
    c, s = client
    _connect(s, "https://www.googleapis.com/auth/gmail.modify")
    r = c.post("/mail/api/trash/empty")
    assert r.status_code == 403


def test_empty_trash_ok_with_scope(client, monkeypatch):
    c, s = client
    _connect(s, "https://mail.google.com/")
    import app.routers.mail as mailmod
    monkeypatch.setattr(mailmod.gmail, "empty_trash", lambda db, uid: {"deleted": 3, "failed": 0})
    r = c.post("/mail/api/trash/empty")
    assert r.status_code == 200
    assert r.json() == {"deleted": 3, "failed": 0}
