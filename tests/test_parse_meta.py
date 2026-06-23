from app.services.deliverables_parser import merge_template_blocks


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
