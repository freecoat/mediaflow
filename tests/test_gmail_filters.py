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
                         scopes="https://www.googleapis.com/auth/gmail.settings.basic",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()
    return s


def test_list_filters(monkeypatch):
    s = _session()
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "filter": [{"id": "F1", "criteria": {"from": "x@y.com"}, "action": {"addLabelIds": ["L1"]}}]})
    out = gmail.list_filters(s, 1)
    assert out[0]["id"] == "F1"


def test_create_filter_strips_empty(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["method"] = m; captured["path"] = p; captured["body"] = body
        return {"id": "F9"}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.create_filter(s, 1, {"from": "boss@x.com", "to": "", "hasAttachment": False},
                              {"addLabelIds": ["L1"], "removeLabelIds": []})
    assert out["id"] == "F9"
    assert captured["method"] == "POST" and captured["path"] == "/settings/filters"
    # criteria vuoti rimossi
    assert captured["body"]["criteria"] == {"from": "boss@x.com"}
    assert captured["body"]["action"] == {"addLabelIds": ["L1"]}


def test_create_filter_needs_criteria_and_action(monkeypatch):
    s = _session()
    monkeypatch.setattr(gmail, "_gmail_request", lambda *a, **k: {"id": "x"})
    assert gmail.create_filter(s, 1, {}, {"addLabelIds": ["L1"]}) is None
    assert gmail.create_filter(s, 1, {"from": "a@b.com"}, {}) is None


def test_delete_filter(monkeypatch):
    s = _session()
    captured = {}
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: captured.update(method=m, path=p) or {})
    assert gmail.delete_filter(s, 1, "F1") is True
    assert captured["method"] == "DELETE" and captured["path"] == "/settings/filters/F1"


def test_get_vacation(monkeypatch):
    s = _session()
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "enableAutoReply": True, "responseSubject": "Ferie"})
    v = gmail.get_vacation(s, 1)
    assert v["enableAutoReply"] is True and v["responseSubject"] == "Ferie"


def test_set_vacation(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["method"] = m; captured["path"] = p; captured["body"] = body
        return body
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.set_vacation(s, 1, enabled=True, subject="Fuori sede",
                             body_html="<p>Torno lunedì</p>", restrict_to_contacts=True, start_ms=1000)
    assert captured["method"] == "PUT" and captured["path"] == "/settings/vacation"
    assert out["enableAutoReply"] is True
    assert out["restrictToContacts"] is True
    assert out["startTime"] == 1000


def test_filters_best_effort_on_error(monkeypatch):
    s = _session()
    def boom(*a, **k): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.list_filters(s, 1) == []
    assert gmail.create_filter(s, 1, {"from": "a@b.com"}, {"addLabelIds": ["L1"]}) is None
    assert gmail.delete_filter(s, 1, "F1") is False
    assert gmail.get_vacation(s, 1) == {}
    assert gmail.set_vacation(s, 1, enabled=False) is None
