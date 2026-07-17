"""Sotto-fase 2a — azioni Gmail-native (modify/trash/apply_action) + counts."""
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
    s.commit()
    return s


def _connect(s):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         scopes="https://www.googleapis.com/auth/gmail.modify",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def test_has_mail_full_scope_true_for_full_scope():
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="openid https://mail.google.com/")
    assert gmail.has_mail_full_scope(row) is True


def test_has_mail_full_scope_false_for_modify_only():
    row = UserOAuthToken(user_id=1, provider="google",
                         scopes="https://www.googleapis.com/auth/gmail.modify")
    assert gmail.has_mail_full_scope(row) is False


def test_has_mail_full_scope_false_when_no_row():
    assert gmail.has_mail_full_scope(None) is False


def test_has_mail_full_scope_false_when_no_scopes_attr():
    row = UserOAuthToken(user_id=1, provider="google", scopes=None)
    assert gmail.has_mail_full_scope(row) is False


def test_modify_thread_sends_add_remove(monkeypatch):
    s = _session(); _connect(s)
    calls = []
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: (calls.append((m, p, body)), {})[1])
    assert gmail.modify_thread(s, 1, "T1", add_labels=["STARRED"], remove_labels=["UNREAD"]) is True
    m, p, body = calls[0]
    assert m == "POST" and p == "/threads/T1/modify"
    assert body == {"addLabelIds": ["STARRED"], "removeLabelIds": ["UNREAD"]}


def test_apply_action_read_removes_unread(monkeypatch):
    s = _session(); _connect(s)
    bodies = []
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: (bodies.append(body), {})[1])
    out = gmail.apply_action(s, 1, ["T1", "T2"], "read")
    assert out == {"ok": 2, "failed": 0}
    assert all(b["removeLabelIds"] == ["UNREAD"] for b in bodies)


def test_apply_action_spam(monkeypatch):
    s = _session(); _connect(s)
    bodies = []
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: (bodies.append(body), {})[1])
    gmail.apply_action(s, 1, ["T1"], "spam")
    assert bodies[0] == {"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]}


def test_apply_action_move_uses_label(monkeypatch):
    s = _session(); _connect(s)
    bodies = []
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: (bodies.append(body), {})[1])
    gmail.apply_action(s, 1, ["T1"], "move", label_id="Label_5")
    assert bodies[0] == {"addLabelIds": ["Label_5"], "removeLabelIds": ["INBOX"]}


def test_apply_action_move_without_label_fails(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: {})
    out = gmail.apply_action(s, 1, ["T1"], "move", label_id=None)
    assert out == {"ok": 0, "failed": 1}


def test_apply_action_trash(monkeypatch):
    s = _session(); _connect(s)
    calls = []
    monkeypatch.setattr(gmail, "_gmail_request",
                        lambda m, p, t, params=None, body=None: (calls.append(p), {})[1])
    out = gmail.apply_action(s, 1, ["T1"], "trash")
    assert out == {"ok": 1, "failed": 0}
    assert calls[0] == "/threads/T1/trash"


def test_list_labels_counts(monkeypatch):
    s = _session(); _connect(s)

    def fake(m, p, t, params=None, body=None):
        if p == "/labels":
            return {"labels": [{"id": "INBOX", "name": "INBOX", "type": "system"}]}
        return {"threadsUnread": 7}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.list_labels(s, 1, counts=True)
    assert out[0]["threads_unread"] == 7
