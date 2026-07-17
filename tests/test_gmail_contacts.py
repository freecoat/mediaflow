"""α.172.247 — autocomplete indirizzi (People API) + enrichment lista thread."""
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
                         scopes="https://www.googleapis.com/auth/contacts.readonly",
                         expires_at=now_utc() + timedelta(hours=1)))
    s.commit()


def test_list_contacts_merges_connections_and_other(monkeypatch):
    s = _session(); _connect(s)

    def fake_people(path, token, params=None):
        if path == "/people/me/connections":
            return {"connections": [
                {"names": [{"displayName": "Al"}], "emailAddresses": [{"value": "al@x.com"}]}]}
        return {"otherContacts": [{"emailAddresses": [{"value": "bo@y.com"}]}]}
    monkeypatch.setattr(gmail, "_people_request", fake_people)
    out = gmail.list_contacts(s, 1)
    emails = {c["email"] for c in out}
    assert emails == {"al@x.com", "bo@y.com"}
    assert next(c for c in out if c["email"] == "al@x.com")["name"] == "Al"


def test_list_contacts_dedup_case_insensitive(monkeypatch):
    s = _session(); _connect(s)

    def fake_people(path, token, params=None):
        if path == "/people/me/connections":
            return {"connections": [{"emailAddresses": [{"value": "Dup@X.com"}]}]}
        return {"otherContacts": [{"emailAddresses": [{"value": "dup@x.com"}]}]}
    monkeypatch.setattr(gmail, "_people_request", fake_people)
    out = gmail.list_contacts(s, 1)
    assert len(out) == 1


def test_list_contacts_no_token():
    s = _session()  # nessun token
    assert gmail.list_contacts(s, 1) == []


def test_list_threads_enriched_with_headers(monkeypatch):
    s = _session(); _connect(s)

    def fake(m, p, t, params=None, body=None):
        if p == "/threads":
            return {"threads": [{"id": "T1", "snippet": "ciao"}]}
        # threads.get metadata
        return {"messages": [{"labelIds": ["UNREAD"], "payload": {"headers": [
            {"name": "From", "value": "Bob <bob@x.com>"},
            {"name": "Subject", "value": "Ping"},
            {"name": "Date", "value": "Mon, 07 Jul 2026 10:00:00 +0000"}]}}]}
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.list_threads(s, 1)
    t = out["threads"][0]
    assert t["subject"] == "Ping"
    assert t["from"] == "Bob <bob@x.com>"
    assert t["unread"] is True


def test_list_threads_enrich_best_effort_on_meta_error(monkeypatch):
    s = _session(); _connect(s)

    def fake(m, p, t, params=None, body=None):
        if p == "/threads":
            return {"threads": [{"id": "T1", "snippet": "ciao"}]}
        raise RuntimeError("meta down")
    monkeypatch.setattr(gmail, "_gmail_request", fake)
    out = gmail.list_threads(s, 1)
    assert out["threads"][0]["id"] == "T1"  # snippet resta, nessuna eccezione
