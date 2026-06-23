from app.services.deliverables_parser import merge_template_blocks
from app.services import deliverables_parser as dp


class _FakeProvider:
    def __init__(self):
        self.calls = 0
    def extract_json(self, system, user, max_tokens=3000):
        self.calls += 1
        return {"name": f"chunk{self.calls}", "video_specs": {"codec": "ProRes"},
                "ai_confidence": 0.9}


def test_single_pass_one_call(monkeypatch):
    prov = _FakeProvider()
    out = dp.parse_delivery_template("short capitolato text " * 10, provider=prov,
                                     model_tier="strong")
    assert prov.calls == 1
    assert out["parse_meta"]["chunked"] is False
    assert out["parse_meta"]["n_chunks"] == 1
    assert out["parse_meta"]["model_tier"] == "strong"


def test_oversized_triggers_chunking(monkeypatch):
    prov = _FakeProvider()
    big = "A" * 200_000  # > MAX_CHARS_SINGLE
    out = dp.parse_delivery_template(big, provider=prov, model_tier="strong")
    assert prov.calls >= 2
    assert out["parse_meta"]["chunked"] is True
    assert out["parse_meta"]["n_chunks"] >= 2


def test_merge_non_null_wins_and_lists_concat():
    parts = [
        {"video_specs": {"codec": "ProRes"}, "audio_specs": {},
         "video_resolution_list": None,
         "ai_confidence": 0.5},
        {"video_specs": {}, "audio_specs": {"codec": "PCM"},
         "ai_confidence": 0.8},
    ]
    merged, warnings = merge_template_blocks(parts)
    assert merged["video_specs"]["codec"] == "ProRes"
    assert merged["audio_specs"]["codec"] == "PCM"
    assert merged["ai_confidence"] == 0.8
    assert warnings == []


def test_merge_list_keys_dedupe():
    parts = [
        {"deliverables": [{"name": "A"}, {"name": "B"}]},
        {"deliverables": [{"name": "B"}, {"name": "C"}]},
    ]
    merged, _ = merge_template_blocks(parts)
    names = [d["name"] for d in merged["deliverables"]]
    assert names == ["A", "B", "C"]


def test_merge_scalar_conflict_warns():
    parts = [
        {"name": "Paramount A"},
        {"name": "Paramount B"},
    ]
    merged, warnings = merge_template_blocks(parts)
    assert merged["name"] == "Paramount A"
    assert any("name" in w for w in warnings)


# ── build_parse_warnings tests (Task 5) ──────────────────────
from app.services.deliverables_parser import build_parse_warnings


def test_warn_weak_model_large_doc():
    assert "weak_model_large_doc" in build_parse_warnings("weak", 50_000, 0.9, False)


def test_no_warn_strong_model_small_doc():
    assert build_parse_warnings("strong", 5_000, 0.9, False) == []


def test_warn_low_confidence():
    assert "low_confidence" in build_parse_warnings("strong", 5_000, 0.3, False)


def test_warn_truncated():
    assert "truncated" in build_parse_warnings("strong", 700_000, 0.9, True)
