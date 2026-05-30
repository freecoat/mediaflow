"""Test export/import capitolati ZIP — v3.5.0-alpha.172.143.

Copre la ricostruzione di un DeliveryTemplate da dict (shape _dt_dict) e la
risoluzione conflitti di code (-IMP). Lo ZIP plumbing (zipfile/Response) è
stdlib + verificato via browser; qui si testa la logica di reconstruction.
"""
import pytest
from app.models import models as m
from app.routers.delivery_templates import _import_one_template, _dt_dict


def _sample_dict(code="NETFLIX-HDR", name="Netflix HDR"):
    return {
        "code": code, "name": name, "broadcaster": "Netflix", "version": "2.0",
        "description": "test",
        "video_specs": {"resolution": "3840x2160", "hdr": "Dolby Vision"},
        "audio_specs": {"channels": "5.1"},
        "text_specs": {}, "head_format": {}, "textless_format": {},
        "naming_convention": {"pattern": "{title}_{lang}"},
        "archive_specs": {}, "metadata_requirements": {},
        "suggested_items": [{"name": "Master UHD", "qty": 1}],
        "ai_generated": True, "ai_confidence": 0.9,
        "default_tc_start": "01:00:00:00",
        "default_timeline_segments": [{"kind": "bars", "tc": "00:59:30:00"}],
    }


def test_import_creates_template_with_blocks(db):
    res = _import_one_template(db, _sample_dict())
    assert res["status"] == "created"
    db.commit()
    t = db.query(m.DeliveryTemplate).filter_by(code="NETFLIX-HDR").first()
    assert t is not None
    assert t.video_specs["hdr"] == "Dolby Vision"
    assert t.naming_convention["pattern"] == "{title}_{lang}"
    assert t.suggested_items == [{"name": "Master UHD", "qty": 1}]
    assert t.default_tc_start == "01:00:00:00"
    assert t.ai_generated is True


def test_import_conflict_renames_with_imp_suffix(db):
    _import_one_template(db, _sample_dict()); db.commit()
    res2 = _import_one_template(db, _sample_dict()); db.commit()
    assert res2["status"] == "renamed"
    assert res2["code"] == "NETFLIX-HDR-IMP"
    assert res2["orig_code"] == "NETFLIX-HDR"
    res3 = _import_one_template(db, _sample_dict()); db.commit()
    assert res3["code"] == "NETFLIX-HDR-IMP2"


def test_import_missing_code_is_error(db):
    res = _import_one_template(db, {"name": "senza code"})
    assert res["status"] == "error"


def test_import_empty_blocks_become_none(db):
    d = _sample_dict(code="EMPTY-1", name="Empty")
    res = _import_one_template(db, d); db.commit()
    t = db.query(m.DeliveryTemplate).filter_by(code="EMPTY-1").first()
    # blocchi {} → None (non dict vuoto)
    assert t.text_specs is None
    assert t.archive_specs is None
    assert t.video_specs is not None  # popolato


def test_roundtrip_dict_export_import(db):
    # crea, serializza via _dt_dict, re-importa → equivalente
    _import_one_template(db, _sample_dict(code="RT-1", name="RoundTrip")); db.commit()
    t = db.query(m.DeliveryTemplate).filter_by(code="RT-1").first()
    exported = _dt_dict(t)
    exported.pop("id", None)
    exported["code"] = "RT-2"  # evita conflitto
    _import_one_template(db, exported); db.commit()
    t2 = db.query(m.DeliveryTemplate).filter_by(code="RT-2").first()
    assert t2.video_specs == t.video_specs
    assert t2.naming_convention == t.naming_convention
    assert t2.default_timeline_segments == t.default_timeline_segments
