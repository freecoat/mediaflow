"""Tests per i helpers deterministici di capitolato_head_extractor (Step 2 Task 2).
Nessuna chiamata LLM reale: solo _taxonomy_vocab e _parse_head_json.
"""
from app.services.capitolato_head_extractor import _taxonomy_vocab, _parse_head_json


def test_taxonomy_vocab_lists_names(db, tenant_id):
    from app.models.models import AudioChannelConfig, AudioMixType
    db.add(AudioChannelConfig(tenant_id=None, name="5.1", channel_count=6))
    db.add(AudioMixType(tenant_id=None, name="M&E"))
    db.flush()
    v = _taxonomy_vocab(db, tenant_id)
    assert "5.1" in v["channel_config"]
    assert "M&E" in v["mix_type"]
    assert "codec" in v and "mix_standard" in v


def test_parse_head_json_tolerant():
    raw = '```json\n{"default_tc_start":"00:59:59:00","timeline_segments":[],"audio_config_codes":[]}\n```'
    d = _parse_head_json(raw)
    assert d["default_tc_start"] == "00:59:59:00"
    assert d["audio_config_codes"] == []


def test_parse_head_json_garbage_returns_empty():
    d = _parse_head_json("non sono json")
    assert d == {}
