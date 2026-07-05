# tests/test_oauth_refresh.py
from datetime import timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, UserOAuthToken
from app.services import oauth_providers as oauth
from app.services.clock import now_utc


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False, future=True)()


def test_returns_current_token_when_not_expired(monkeypatch):
    s = _session()
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="live-abc",
                         expires_at=now_utc() + timedelta(hours=1))); s.commit()
    # non deve chiamare la rete
    monkeypatch.setattr(oauth, "_http_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no net")))
    assert oauth.get_valid_access_token(s, 1, "google") == "live-abc"


def test_refreshes_when_expired(monkeypatch):
    s = _session()
    s.add(UserOAuthToken(user_id=1, provider="google", access_token="old",
                         refresh_token_enc=oauth.encrypt_refresh_token("rt-xyz"),
                         expires_at=now_utc() - timedelta(minutes=5))); s.commit()
    calls = {}

    def fake_post(url, data):
        calls["grant"] = data.get("grant_type")
        calls["rt"] = data.get("refresh_token")
        return {"access_token": "new-token", "expires_in": 3600}

    monkeypatch.setattr(oauth, "_http_post", fake_post)
    tok = oauth.get_valid_access_token(s, 1, "google")
    assert tok == "new-token"
    assert calls["grant"] == "refresh_token"
    assert calls["rt"] == "rt-xyz"
    row = oauth.get_token(s, 1, "google")
    assert row.access_token == "new-token"
    assert row.expires_at > now_utc()


def test_returns_none_when_no_token():
    s = _session()
    assert oauth.get_valid_access_token(s, 99, "google") is None
