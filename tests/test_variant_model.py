"""Unit test modelli Bundle L Stack 1."""
from datetime import datetime
import pytest
from sqlalchemy.exc import IntegrityError
from app.models.variant import VariantSchemaVersion, DeliveryVariant, DeliveryVariantCategory


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
    with pytest.raises(IntegrityError):
        db.commit()


def test_delivery_variant_create(db, tenant_id):
    from app.models.variant import DeliveryVariant, DeliveryVariantCategory, VariantSchemaVersion
    sv = VariantSchemaVersion(version="v1", schema_json={"type": "object"})
    db.add(sv); db.commit(); db.refresh(sv)

    v = DeliveryVariant(
        tenant_id=tenant_id,
        code="imf-master-hd-it",
        name="IMF Master HD — Italiano",
        category=DeliveryVariantCategory.t1_technical,
        schema_version_id=sv.id,
        spec_json={"container": {"format": "IMF"}, "language": "it"},
        language="it",
        territory="WW",
        delivery_format="IMF",
        has_textless=False,
        has_subtitles=False,
    )
    db.add(v); db.commit(); db.refresh(v)
    assert v.id is not None
    assert v.category == DeliveryVariantCategory.t1_technical
    assert v.spec_json["container"]["format"] == "IMF"


def test_delivery_variant_unique_code_per_tenant(db, tenant_id):
    from app.models.variant import DeliveryVariant, VariantSchemaVersion
    sv = VariantSchemaVersion(version="v1", schema_json={})
    db.add(sv); db.commit(); db.refresh(sv)
    db.add(DeliveryVariant(tenant_id=tenant_id, code="dup", name="A", schema_version_id=sv.id, spec_json={}))
    db.commit()
    db.add(DeliveryVariant(tenant_id=tenant_id, code="dup", name="B", schema_version_id=sv.id, spec_json={}))
    with pytest.raises(IntegrityError):
        db.commit()


def test_jobdeliverable_variant_link(db, tenant_id):
    from app.models import (
        Tenant, Client, Project, Job, JobDeliverable,
        DeliveryVariant, VariantSchemaVersion, DeliveryVariantCategory,
    )
    db.add(Tenant(id=tenant_id, name="t", slug="t"))
    db.add(Client(id=1, tenant_id=tenant_id, name="C"))
    db.add(Project(id=1, tenant_id=tenant_id, code="P1", title="P", client_id=1))
    db.add(Job(id=1, tenant_id=tenant_id, code="J1", title="J", project_id=1, client_id=1))
    sv = VariantSchemaVersion(version="v1", schema_json={})
    db.add(sv); db.commit(); db.refresh(sv)
    v = DeliveryVariant(
        tenant_id=tenant_id, code="x", name="X",
        category=DeliveryVariantCategory.t1_technical,
        schema_version_id=sv.id, spec_json={},
        language="it", territory="WW", delivery_format="IMF",
    )
    db.add(v); db.commit(); db.refresh(v)

    d = JobDeliverable(
        tenant_id=tenant_id, job_id=1, name="DLV-1",
        variant_id=v.id,
        variant_language="it", variant_territory="WW", variant_format="IMF",
    )
    db.add(d); db.commit(); db.refresh(d)
    assert d.variant_id == v.id
    assert d.variant_language == "it"
    assert d.variant_format == "IMF"
