import pytest
from unittest.mock import patch
from app.services.ai_provider import (
    parse_model_tier, rank_parse_models, pick_parse_provider, ProviderConfig,
)
from app.models.models import UserAISettings


def test_tier_strong_for_sonnet_and_gpt4o():
    assert parse_model_tier("claude", "claude-sonnet-4-6") == "strong"
    assert parse_model_tier("claude", "claude-opus-4-8") == "strong"
    assert parse_model_tier("openai", "gpt-4o") == "strong"
    assert parse_model_tier("gemini", "gemini-2.0-pro") == "strong"


def test_tier_medium_for_haiku_flash_mini():
    assert parse_model_tier("claude", "claude-haiku-4-5") == "medium"
    assert parse_model_tier("gemini", "gemini-2.0-flash") == "medium"
    assert parse_model_tier("openai", "gpt-4o-mini") == "medium"


def test_tier_weak_for_deepseek_ollama_sonar_and_unknown():
    assert parse_model_tier("deepseek", "deepseek-v4-flash") == "weak"
    assert parse_model_tier("ollama", "llama3.1:70b") == "weak"
    assert parse_model_tier("perplexity", "sonar-pro") == "weak"
    assert parse_model_tier("whoknows", None) == "weak"


def test_rank_picks_strong_over_weak():
    rows = [
        UserAISettings(user_id=1, provider="deepseek", model="deepseek-v4-flash",
                       api_key_encrypted="x"),
        UserAISettings(user_id=1, provider="claude", model="claude-sonnet-4-6",
                       api_key_encrypted="x"),
    ]
    best, tier = rank_parse_models(rows)
    assert best.provider == "claude"
    assert tier == "strong"


def test_rank_only_weak_returns_weak():
    rows = [UserAISettings(user_id=1, provider="deepseek",
                           model="deepseek-v4-flash", api_key_encrypted="x")]
    best, tier = rank_parse_models(rows)
    assert best.provider == "deepseek"
    assert tier == "weak"


def test_rank_empty_returns_none():
    assert rank_parse_models([]) is None


@pytest.fixture
def db_with_user():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.models import Base, User, Tenant, UserRole
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    u = User(id=1, tenant_id=1, email="a@t.local", full_name="A",
             hashed_password="x", role=UserRole.admin, is_active=True)
    s.add(u); s.commit()
    yield s, u
    s.close()


def _add_ai(s, uid, provider, model, key="enc"):
    from app.models.models import UserAISettings
    s.add(UserAISettings(user_id=uid, provider=provider, model=model,
                         api_key_encrypted=key))
    s.commit()


def test_list_parse_models_ranked_with_strongest_flag(db_with_user):
    from app.services.ai_provider import list_parse_models
    s, u = db_with_user
    _add_ai(s, u.id, "deepseek", "deepseek-v4-flash")
    _add_ai(s, u.id, "claude", "claude-sonnet-4-6")
    models = list_parse_models(u.id, s)
    assert [m["provider"] for m in models] == ["claude", "deepseek"]
    assert models[0]["tier"] == "strong"
    assert models[0]["is_strongest"] is True
    assert models[1]["is_strongest"] is False
    assert "claude" in models[0]["label"].lower() or "anthropic" in models[0]["label"].lower()


def test_list_parse_models_empty_without_config(db_with_user):
    from app.services.ai_provider import list_parse_models
    s, u = db_with_user
    assert list_parse_models(u.id, s) == []


def test_pick_override_forces_weaker_provider(db_with_user, monkeypatch):
    """Override esplicito 'deepseek' deve vincere sul ranking (che sceglierebbe Claude)."""
    import app.services.ai_provider as ai
    s, u = db_with_user
    _add_ai(s, u.id, "deepseek", "deepseek-v4-flash")
    _add_ai(s, u.id, "claude", "claude-sonnet-4-6")
    monkeypatch.setattr(ai, "decrypt_secret", lambda x: "k", raising=False)
    monkeypatch.setattr(ai, "build_provider", lambda cfg: type("P", (), {"name": cfg.provider})())
    monkeypatch.setattr(ai, "_apply_content_lockdown", lambda cfg, uid, db: cfg)
    prov, tier, label = ai.pick_parse_provider(u.id, s, override_provider="deepseek")
    assert prov.name == "deepseek"
    assert tier == "weak"


def test_pick_uses_stored_pref_when_no_override(db_with_user, monkeypatch):
    """User.parse_ai_provider salvato deve essere rispettato senza override esplicito."""
    import app.services.ai_provider as ai
    s, u = db_with_user
    _add_ai(s, u.id, "deepseek", "deepseek-v4-flash")
    _add_ai(s, u.id, "claude", "claude-sonnet-4-6")
    u.parse_ai_provider = "deepseek"; s.commit()
    monkeypatch.setattr(ai, "build_provider", lambda cfg: type("P", (), {"name": cfg.provider})())
    monkeypatch.setattr(ai, "_apply_content_lockdown", lambda cfg, uid, db: cfg)
    prov, tier, label = ai.pick_parse_provider(u.id, s)
    assert prov.name == "deepseek"


def test_pick_falls_back_to_strongest_when_pref_unconfigured(db_with_user, monkeypatch):
    """Pref che punta a provider NON configurato → ricade su automatico (Claude)."""
    import app.services.ai_provider as ai
    s, u = db_with_user
    _add_ai(s, u.id, "claude", "claude-sonnet-4-6")
    u.parse_ai_provider = "openai"; s.commit()   # openai non configurato
    monkeypatch.setattr(ai, "build_provider", lambda cfg: type("P", (), {"name": cfg.provider})())
    monkeypatch.setattr(ai, "_apply_content_lockdown", lambda cfg, uid, db: cfg)
    prov, tier, label = ai.pick_parse_provider(u.id, s)
    assert prov.name == "claude"


def test_pick_parse_provider_global_path_returns_none_on_build_failure():
    """pick_parse_provider(None, None) must return None (not raise) when
    build_provider raises — parity with the user-present path."""
    good_cfg = ProviderConfig(provider="claude", api_key="fake", model="claude-sonnet-4-6")
    with patch("app.services.ai_provider._global_config", return_value=good_cfg), \
         patch("app.services.ai_provider._apply_content_lockdown", return_value=good_cfg), \
         patch("app.services.ai_provider.build_provider", side_effect=RuntimeError("no key")):
        result = pick_parse_provider(None, None)
    assert result is None
