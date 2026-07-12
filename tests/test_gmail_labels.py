from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, UserOAuthToken
from app.services.clock import now_utc
from app.services import gmail


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False, future=True)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, is_active=True))
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         scopes="https://www.googleapis.com/auth/gmail.modify",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()
    return s


def test_create_label_flat(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["method"] = m; captured["path"] = p; captured["body"] = body
        return {"id": "Label_9", "name": body["name"], "type": "user"}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.create_label(s, 1, "Clienti")
    assert out == {"id": "Label_9", "name": "Clienti", "type": "user"}
    assert captured["method"] == "POST" and captured["path"] == "/labels"
    assert captured["body"]["name"] == "Clienti"


def test_create_label_nested(monkeypatch):
    s = _session()
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: {"id": "L1", "name": body["name"], "type": "user"})
    out = gmail.create_label(s, 1, "A24", parent="Clienti")
    assert out["name"] == "Clienti/A24"


def test_create_label_empty_name_none(monkeypatch):
    s = _session()
    monkeypatch.setattr(gmail, "_gmail_request", lambda *a, **k: {"id": "x"})
    assert gmail.create_label(s, 1, "   ") is None


def test_rename_label_patch(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["method"] = m; captured["path"] = p; captured["body"] = body
        return {"id": "L1", "name": body["name"], "type": "user"}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.rename_label(s, 1, "L1", "Fornitori")
    assert out["name"] == "Fornitori"
    assert captured["method"] == "PATCH" and captured["path"] == "/labels/L1"


def test_delete_label_ok(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["method"] = m; captured["path"] = p; return {}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    assert gmail.delete_label(s, 1, "L1") is True
    assert captured["method"] == "DELETE" and captured["path"] == "/labels/L1"


def test_label_ops_best_effort_on_error(monkeypatch):
    s = _session()
    def boom(*a, **k): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.create_label(s, 1, "X") is None
    assert gmail.rename_label(s, 1, "L1", "Y") is None
    assert gmail.delete_label(s, 1, "L1") is False
