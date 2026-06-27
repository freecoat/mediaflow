import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant
import app.services.ai_assistant as aa


@pytest.fixture
def db():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    s = sessionmaker(bind=e, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True,
                 web_sources=["filmitalia.org", "imdb.com"])); s.commit()
    yield s
    s.close()


def test_web_search_passes_configured_domains(db, monkeypatch):
    captured = {}
    monkeypatch.setattr("app.services.egress_guard.web_search_allowed_current", lambda d: True)
    def fake_tavily(query, max_results=5, search_depth="basic", timeout=15, include_domains=None):
        captured["include_domains"] = include_domains
        return [{"title": "x", "url": "u", "content": "c"}]
    monkeypatch.setattr("app.services.web_search.tavily_search", fake_tavily)
    out = aa._h_web_search(db, {"query": "Lucky Red film 2026"})
    assert out["results"] is not None
    assert captured["include_domains"] == ["filmitalia.org", "imdb.com"]


def test_web_search_no_domains_when_empty(db, monkeypatch):
    db.query(Tenant).filter(Tenant.id == 1).first().web_sources = []
    db.commit()
    captured = {}
    monkeypatch.setattr("app.services.egress_guard.web_search_allowed_current", lambda d: True)
    monkeypatch.setattr("app.services.web_search.tavily_search",
        lambda query, **k: captured.update(k) or [{"title": "x", "url": "u", "content": "c"}])
    aa._h_web_search(db, {"query": "q"})
    assert captured.get("include_domains") in (None, [])
