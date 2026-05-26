"""Unit test modelli Bundle L Stack 1."""
from datetime import datetime
from app.models.variant import VariantSchemaVersion


def test_variant_schema_version_create(db):
    v = VariantSchemaVersion(
        version="v1",
        schema_json={"$schema": "https://json-schema.org/draft-07/schema", "type": "object"},
        description="Initial canonical schema",
        is_active=True,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    assert v.id is not None
    assert v.version == "v1"
    assert v.is_active is True
    assert isinstance(v.created_at, datetime)


def test_variant_schema_version_unique(db):
    db.add(VariantSchemaVersion(version="v1", schema_json={}))
    db.commit()
    db.add(VariantSchemaVersion(version="v1", schema_json={}))
    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        db.commit()
