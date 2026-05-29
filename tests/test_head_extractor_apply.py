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


# ── Task 3: apply_head_specs ──────────────────────────────────────────────────

from app.services.capitolato_head_extractor import apply_head_specs


def _tpl(db, tenant_id, code="RAI-AP"):
    from app.models.models import DeliveryTemplate
    t = DeliveryTemplate(tenant_id=tenant_id, code=code, name=code)
    db.add(t); db.flush()
    return t


def test_apply_sets_defaults_and_creates_presets(db, tenant_id):
    from app.models.models import AudioConfigPreset
    t = _tpl(db, tenant_id)
    parsed = {
        "default_tc_start": "00:59:59:00", "default_program_start": "01:00:00:00",
        "timeline_segments": [{"order": 1, "kind": "bars_tone", "label": "barre"}],
        "audio_config_codes": [
            {"code": "8T07", "name": "8 tracce", "tracks": [{"track_label": "T1", "channel_config": "5.1"}]},
        ],
        "suggested_taxonomy": [{"kind": "mix_type", "name": "Audiodescrizione", "seen_as": "AD"}],
    }
    out = apply_head_specs(db, t.id, parsed, tenant_id)
    db.flush(); db.refresh(t)
    assert t.default_tc_start == "00:59:59:00"
    assert t.default_program_start == "01:00:00:00"
    assert t.default_timeline_segments[0]["kind"] == "bars_tone"
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.delivery_template_id == t.id, AudioConfigPreset.code == "8T07").first()
    assert p is not None and p.track_layout[0]["channel_config"] == "5.1"
    assert out["presets_created"] == 1
    assert out["suggested_taxonomy"] == parsed["suggested_taxonomy"]


def test_apply_is_idempotent_upsert(db, tenant_id):
    from app.models.models import AudioConfigPreset
    t = _tpl(db, tenant_id, code="RAI-AP2")
    parsed = {"audio_config_codes": [{"code": "8T07", "name": "v1", "tracks": []}]}
    apply_head_specs(db, t.id, parsed, tenant_id); db.flush()
    parsed["audio_config_codes"][0]["name"] = "v2"
    out = apply_head_specs(db, t.id, parsed, tenant_id); db.flush()
    presets = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.delivery_template_id == t.id, AudioConfigPreset.code == "8T07").all()
    assert len(presets) == 1
    assert presets[0].name == "v2"
    assert out["presets_updated"] == 1 and out["presets_created"] == 0


def test_apply_empty_preview_does_not_wipe(db, tenant_id):
    t = _tpl(db, tenant_id, code="RAI-AP3")
    t.default_tc_start = "00:59:59:00"; db.flush()
    apply_head_specs(db, t.id, {"default_tc_start": None, "timeline_segments": [], "audio_config_codes": []}, tenant_id)
    db.flush(); db.refresh(t)
    assert t.default_tc_start == "00:59:59:00"


# ── Task 4: alias reconciliation ─────────────────────────────────────────────

from app.services.capitolato_head_extractor import _apply_alias_mapping


def test_apply_alias_mapping_rewrites_and_prunes():
    parsed = {
        "audio_config_codes": [
            {"code": "X", "tracks": [
                {"track_label": "T1", "mix_type": "IT mix", "channel_config": "5.1"},
                {"track_label": "T2", "mix_type": "M&E", "channel_config": "Stereo"},
            ]},
        ],
        "suggested_taxonomy": [
            {"kind": "mix_type", "name": "IT mix", "seen_as": "IT"},
            {"kind": "mix_type", "name": "Foley Stem", "seen_as": "foley"},
        ],
    }
    # mapping says "IT mix" (mix_type) is an alias of canonical "M&E"; "Foley Stem" is NEW
    mapping = {("mix_type", "IT mix"): "M&E"}
    report = _apply_alias_mapping(parsed, mapping)
    # track field rewritten to canonical
    assert parsed["audio_config_codes"][0]["tracks"][0]["mix_type"] == "M&E"
    # aliased suggested term pruned; genuinely-new kept
    names = [s["name"] for s in parsed["suggested_taxonomy"]]
    assert "IT mix" not in names
    assert "Foley Stem" in names
    assert report["mapped"] == [{"kind": "mix_type", "name": "IT mix", "canonical": "M&E"}]
    assert any(s["name"] == "Foley Stem" for s in report["new"])


class _FakeProvider:
    """Provider finto: complete() ritorna un JSON di decisioni prefissato."""
    def __init__(self, raw):
        self._raw = raw

    def complete(self, system, user, max_tokens=2000, temperature=0.0):
        return self._raw


def test_reconcile_maps_alias_to_existing_canonical(db, tenant_id):
    from app.models.models import AudioMixType
    from app.services.capitolato_head_extractor import reconcile_taxonomy_aliases
    db.add(AudioMixType(tenant_id=None, name="M&E")); db.flush()
    parsed = {
        "audio_config_codes": [{"code": "X", "tracks": [{"track_label": "T1", "mix_type": "IT mix"}]}],
        "suggested_taxonomy": [{"kind": "mix_type", "name": "IT mix", "seen_as": "IT"}],
    }
    prov = _FakeProvider('[{"kind":"mix_type","name":"IT mix","canonical":"M&E"}]')
    rep = reconcile_taxonomy_aliases(prov, parsed, db, tenant_id)
    assert parsed["audio_config_codes"][0]["tracks"][0]["mix_type"] == "M&E"
    assert parsed["suggested_taxonomy"] == []          # alias pruned
    assert rep["mapped"] and rep["mapped"][0]["canonical"] == "M&E"


def test_reconcile_rejects_hallucinated_canonical(db, tenant_id):
    from app.services.capitolato_head_extractor import reconcile_taxonomy_aliases
    parsed = {
        "audio_config_codes": [{"code": "X", "tracks": [{"track_label": "T1", "mix_type": "Foley"}]}],
        "suggested_taxonomy": [{"kind": "mix_type", "name": "Foley", "seen_as": "foley"}],
    }
    # LLM "mappa" a una canonica NON presente in vocab -> deve essere ignorata (resta NEW)
    prov = _FakeProvider('[{"kind":"mix_type","name":"Foley","canonical":"Inventato XYZ"}]')
    rep = reconcile_taxonomy_aliases(prov, parsed, db, tenant_id)
    assert parsed["audio_config_codes"][0]["tracks"][0]["mix_type"] == "Foley"  # non riscritto
    assert any(s["name"] == "Foley" for s in parsed["suggested_taxonomy"])      # resta nuovo
    assert rep["mapped"] == []
