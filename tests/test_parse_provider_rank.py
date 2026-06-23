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


def test_pick_parse_provider_global_path_returns_none_on_build_failure():
    """pick_parse_provider(None, None) must return None (not raise) when
    build_provider raises — parity with the user-present path."""
    good_cfg = ProviderConfig(provider="claude", api_key="fake", model="claude-sonnet-4-6")
    with patch("app.services.ai_provider._global_config", return_value=good_cfg), \
         patch("app.services.ai_provider._apply_content_lockdown", return_value=good_cfg), \
         patch("app.services.ai_provider.build_provider", side_effect=RuntimeError("no key")):
        result = pick_parse_provider(None, None)
    assert result is None
