"""Test parse_capitolati batch script.

Usa file fixture testo creato in test (no chiamate AI reali in CI).
"""
from pathlib import Path
import pytest


def test_classify_item_by_keyword():
    """Classificazione T1/T2/T3 via keyword heuristic (no AI in unit test)."""
    from scripts.parse_capitolati import classify_item_tier

    assert classify_item_tier("IMF Master HD 1920x1080 ProRes") == "t1_technical"
    assert classify_item_tier("DCP package Smpte 2K") == "t1_technical"
    assert classify_item_tier("Trailer 60s textless pack") == "t1_technical"
    assert classify_item_tier("LTO archive verificato MD5") == "t1_technical"
    assert classify_item_tier("Subtitle file .scc per lingua") == "t1_technical"
    assert classify_item_tier("CDL color decision list") == "t2_documentation"
    assert classify_item_tier("Spotting list dialogo IT") == "t2_documentation"
    assert classify_item_tier("Music cue sheet MIDEM") == "t2_documentation"
    assert classify_item_tier("NDA firmato da Produttore") == "t3_compilation"
    assert classify_item_tier("Materials Required form completato") == "t3_compilation"


def test_extract_text_from_txt(tmp_path):
    from scripts.parse_capitolati import extract_text_from_file
    f = tmp_path / "test.txt"
    f.write_text("Hello world\nMaster IMF HD", encoding="utf-8")
    text = extract_text_from_file(str(f))
    assert "Master IMF HD" in text


def test_extract_text_from_unknown_returns_empty():
    from scripts.parse_capitolati import extract_text_from_file
    text = extract_text_from_file("/non/existent/file.xyz")
    assert text == ""


def test_materialize_persists_timeline_and_audio_code(db, tenant_id):
    from app.models.models import DeliveryTemplate, DeliveryItem, AudioConfigPreset
    from app.services.delivery_items_parser import materialize_items
    t = DeliveryTemplate(tenant_id=tenant_id, code="RAI-MZ", name="RAI mz")
    db.add(t); db.flush()
    parsed = {"items": [{
        "name": "HDTV 1080i25", "tc_start": "10:00:00:00",
        "program_start": "10:00:00:00",
        "timeline_segments": [{"order": 1, "kind": "bars_tone", "label": "barre"}],
        "audio_config_code": "8T07",
        "audio_tracks": [{"track_label": "5.1"}],
    }]}
    saved, skipped = materialize_items(db, t.id, parsed, tenant_id)
    assert saved == 1
    it = db.query(DeliveryItem).filter(DeliveryItem.delivery_template_id == t.id).first()
    assert it.tc_start == "10:00:00:00"
    assert it.timeline_segments[0]["kind"] == "bars_tone"
    assert it.audio_config_code == "8T07"
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.delivery_template_id == t.id, AudioConfigPreset.code == "8T07").first()
    assert p is not None
    assert it.audio_config_preset_id == p.id
