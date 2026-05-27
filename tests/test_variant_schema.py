"""Test JSON Schema v1 validation."""
import json
from pathlib import Path
import pytest


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "variant_v1.json"


@pytest.fixture
def schema_v1():
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_schema_loads(schema_v1):
    assert schema_v1["$id"] == "claqo/variant/v1"
    assert schema_v1["type"] == "object"


def test_valid_variant_passes(schema_v1):
    from jsonschema import validate
    instance = {
        "code": "imf-master-hd-it",
        "name": "IMF Master HD IT",
        "category": "t1_technical",
        "container": {"format": "IMF"},
        "video": {"resolution": "1920x1080", "codec": "JPEG2000", "framerate": 25, "bit_depth": 10},
        "language": "it",
        "territory": "WW",
    }
    validate(instance=instance, schema=schema_v1)  # no exception = pass


def test_invalid_code_pattern_fails(schema_v1):
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
    instance = {"code": "INVALID UPPER", "name": "X", "category": "t1_technical"}
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=schema_v1)


def test_unknown_category_fails(schema_v1):
    from jsonschema import validate
    from jsonschema.exceptions import ValidationError
    instance = {"code": "x", "name": "X", "category": "unknown"}
    with pytest.raises(ValidationError):
        validate(instance=instance, schema=schema_v1)


def test_additional_properties_allowed(schema_v1):
    """Back-compat: campi futuri (stack consecutivi) non breakno old variant."""
    from jsonschema import validate
    instance = {
        "code": "x", "name": "XXX", "category": "t1_technical",
        "future_field_2027": {"any": "value"},
    }
    validate(instance=instance, schema=schema_v1)  # no exception
