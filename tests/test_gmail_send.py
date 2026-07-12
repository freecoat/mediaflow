import base64
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
                         scopes="https://www.googleapis.com/auth/gmail.compose",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()
    return s


def _decode_raw(raw_b64):
    return base64.urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4)).decode("utf-8", "replace")


def test_build_mime_basic():
    raw = gmail.build_mime(to="x@y.com", subject="Ciao", body_html="<p>hi</p>")
    txt = _decode_raw(raw)
    assert "To: x@y.com" in txt
    assert "Subject: Ciao" in txt
    assert "hi" in txt


def test_build_mime_reply_headers():
    raw = gmail.build_mime(to="x@y.com", subject="Re: Ciao", body_html="<p>r</p>",
                           in_reply_to="<abc@mail>", references="<abc@mail>")
    txt = _decode_raw(raw)
    assert "In-Reply-To: <abc@mail>" in txt
    assert "References: <abc@mail>" in txt


def test_build_mime_attachment():
    raw = gmail.build_mime(to="x@y.com", subject="A", body_html="<p>a</p>",
                           attachments=[{"filename": "n.txt", "mime_type": "text/plain",
                                         "data": b"hello"}])
    txt = _decode_raw(raw)
    assert "n.txt" in txt


def test_send_message_passes_thread_id(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["path"] = p; captured["body"] = body
        return {"id": "SENT1", "threadId": "T9"}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.send_message(s, 1, to="x@y.com", subject="S", body_html="<p>b</p>", thread_id="T9")
    assert out["id"] == "SENT1"
    assert captured["path"] == "/messages/send"
    assert captured["body"]["threadId"] == "T9"
    assert "raw" in captured["body"]


def test_send_message_best_effort_on_error(monkeypatch):
    s = _session()
    def boom(*a, **k): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.send_message(s, 1, to="x@y.com", subject="S", body_html="b") is None


def test_update_draft_puts_to_draft_id(monkeypatch):
    s = _session()
    captured = {}
    def fake(m, p, t, params=None, body=None):
        captured["method"] = m; captured["path"] = p; captured["body"] = body
        return {"id": "DR1"}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.update_draft(s, 1, "DR1", to="x@y.com", subject="S", body_html="<p>b</p>")
    assert out["id"] == "DR1"
    assert captured["method"] == "PUT"
    assert captured["path"] == "/drafts/DR1"
    assert captured["body"]["id"] == "DR1"
    assert "raw" in captured["body"]["message"]


def test_update_draft_best_effort_on_error(monkeypatch):
    s = _session()
    def boom(*a, **k): raise RuntimeError("HTTP 500")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.update_draft(s, 1, "DR1", to="x@y.com", subject="S", body_html="b") is None


def test_get_attachment_decodes(monkeypatch):
    s = _session()
    payload = base64.urlsafe_b64encode(b"filedata").rstrip(b"=").decode()
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "data": payload, "size": 8})
    assert gmail.get_attachment(s, 1, "M1", "ATT1") == b"filedata"
