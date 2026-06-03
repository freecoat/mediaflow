"""Naming convention strutturata: normalize + resolve cascade (α.172.182)."""
from app.services import naming_resolver as nr


def test_default_tenant_has_video_and_audio():
    d = nr.DEFAULT_TENANT_NAMING_CONVENTIONS
    assert "video" in d and "audio" in d
    assert d["video"]["pattern"] and isinstance(d["video"]["tokens"], list)


def test_normalize_keeps_valid_shape():
    raw = {
        "pattern": "{project_code}_{title}_{date_iso}",
        "tokens": ["project_code", "title", "date_iso"],
        "separator": "_", "allowed_chars": "A-Za-z0-9_-",
        "max_length": 120, "case": "upper", "extension": ".mov",
        "examples": ["MARE_X_2026-06-03.mov"], "source": "capitolato",
    }
    out = nr.normalize_naming_convention(raw)
    assert out["pattern"] == raw["pattern"]
    assert out["case"] == "upper"
    assert out["max_length"] == 120
    assert out["tokens"] == ["project_code", "title", "date_iso"]


def test_normalize_invalid_case_defaults_asis():
    out = nr.normalize_naming_convention({"pattern": "{title}", "case": "SHOUT"})
    assert out["case"] == "asis"


def test_normalize_maxlength_non_int_becomes_none():
    out = nr.normalize_naming_convention({"pattern": "{title}", "max_length": "abc"})
    assert out["max_length"] is None


def test_normalize_unknown_tokens_flagged():
    out = nr.normalize_naming_convention({"pattern": "{project_title}_{nope}", "tokens": ["project_title", "nope"]})
    assert "nope" in out["unknown_tokens"]
    assert "project_title" not in out["unknown_tokens"]


def test_normalize_none_returns_none():
    assert nr.normalize_naming_convention(None) is None
    assert nr.normalize_naming_convention({}) is None


def test_resolve_falls_back_to_tenant_default_when_all_empty():
    conv = nr.resolve_naming_convention(
        db=None, delivery_item=None, delivery_template=None,
        discipline="video", tenant_naming=None,
    )
    assert conv["_source"] == "tenant_default"
    assert conv["pattern"] == nr.DEFAULT_TENANT_NAMING_CONVENTIONS["video"]["pattern"]


def test_resolve_prefers_item_over_template_over_tenant():
    item_conv = {"pattern": "ITEM_{title}", "source": "item"}
    tpl_conv = {"pattern": "TPL_{title}", "source": "capitolato"}
    tenant = {"video": {"pattern": "TENANT_{title}"}}
    r = nr.resolve_naming_convention(db=None, delivery_item_conv=item_conv,
                                     delivery_template_conv=tpl_conv,
                                     discipline="video", tenant_naming=tenant)
    assert r["pattern"] == "ITEM_{title}" and r["_source"] == "item"
    r2 = nr.resolve_naming_convention(db=None, delivery_item_conv=None,
                                      delivery_template_conv=tpl_conv,
                                      discipline="video", tenant_naming=tenant)
    assert r2["pattern"] == "TPL_{title}" and r2["_source"] == "capitolato"


def test_resolve_template_per_discipline_dict():
    tpl_conv = {"video": {"pattern": "V_{title}"}, "audio": {"pattern": "A_{title}"}}
    r = nr.resolve_naming_convention(db=None, delivery_item_conv=None,
                                     delivery_template_conv=tpl_conv,
                                     discipline="audio", tenant_naming=None)
    assert r["pattern"] == "A_{title}" and r["_source"] == "capitolato"


def test_normalize_ai_dirty_output():
    ai = {"pattern": "{film_name}_{resolution}_{lang_audio}",
          "tokens": ["film_name", "resolution", "lang_audio", "weird_token"],
          "case": "UPPER", "max_length": "100", "examples": ["X_UHD_it"]}
    out = nr.normalize_naming_convention(ai)
    assert out["case"] == "upper"
    assert out["max_length"] == 100
    assert "weird_token" in out["unknown_tokens"]
