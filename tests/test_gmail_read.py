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
    s.commit()
    return s


def _connect(s):
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="tok",
                         scopes="https://www.googleapis.com/auth/gmail.readonly",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()


def test_list_threads_ok(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "threads": [{"id": "T1", "snippet": "ciao"}], "nextPageToken": "NXT"})
    out = gmail.list_threads(s, 1, query="from:x@y.com")
    assert out["threads"][0]["id"] == "T1"
    assert out["next_page_token"] == "NXT"


def test_list_threads_best_effort_without_token():
    s = _session()  # nessun token
    assert gmail.list_threads(s, 1) == {"threads": [], "next_page_token": None}


def test_get_thread_normalizes(monkeypatch):
    s = _session(); _connect(s)
    payload = {
        "mimeType": "multipart/mixed",
        "headers": [{"name": "From", "value": "Mitt <m@x.com>"},
                    {"name": "To", "value": "me@t.local"},
                    {"name": "Subject", "value": "Oggetto"},
                    {"name": "Date", "value": "Mon, 7 Jul 2026 10:00:00 +0000"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("testo puro")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>html</p>")}},
            {"mimeType": "application/pdf", "filename": "a.pdf",
             "body": {"attachmentId": "ATT1", "size": 1234}},
        ],
    }
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "id": "T1", "messages": [{"id": "M1", "threadId": "T1", "snippet": "s", "payload": payload}]})
    thr = gmail.get_thread(s, 1, "T1")
    msg = thr["messages"][0]
    assert msg["from"] == "Mitt <m@x.com>"
    assert msg["subject"] == "Oggetto"
    assert msg["body_html"] == "<p>html</p>"
    assert msg["body_text"] == "testo puro"
    assert msg["attachments"][0] == {"id": "ATT1", "filename": "a.pdf",
                                     "mime_type": "application/pdf", "size": 1234}


def test_get_thread_best_effort_on_error(monkeypatch):
    s = _session(); _connect(s)
    def boom(*a, **k): raise RuntimeError("HTTP 403")
    monkeypatch.setattr(gmail, "_gmail_request", boom)
    assert gmail.get_thread(s, 1, "T1") is None


def test_list_labels_ok(monkeypatch):
    s = _session(); _connect(s)
    monkeypatch.setattr(gmail, "_gmail_request", lambda m, p, t, params=None, body=None: {
        "labels": [{"id": "INBOX", "name": "INBOX", "type": "system"},
                   {"id": "Label_1", "name": "Clienti", "type": "user"}]})
    labs = gmail.list_labels(s, 1)
    assert {"id": "INBOX", "name": "INBOX", "type": "system"} in labs
