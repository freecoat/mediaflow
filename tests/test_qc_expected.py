"""Tests for qc_expected_for_deliverable helper (T8 — Task 8).

Verifica che il helper surfaci tc_start, timeline_segments e audio_config_code
per un JobDeliverable collegato a un DeliveryItem, e ritorni None se non collegato.
"""
import pytest
from app.models.models import DeliveryTemplate, DeliveryItem
from app.services.delivery_timeline_service import qc_expected_for_deliverable


def test_qc_expected_for_deliverable(db, tenant_id):
    t = DeliveryTemplate(
        tenant_id=tenant_id,
        code="QC-X",
        name="QC",
        default_tc_start="00:59:59:00",
    )
    db.add(t)
    db.flush()

    di = DeliveryItem(
        tenant_id=tenant_id,
        delivery_template_id=t.id,
        name="D",
        audio_config_code="8T07",
    )
    db.add(di)
    db.flush()

    class _Stub:  # minimal stand-in for a JobDeliverable
        delivery_item_id = di.id

    out = qc_expected_for_deliverable(db, _Stub())
    assert out is not None
    # TC inherited from template default
    assert out["tc_start"] == "00:59:59:00"
    assert out["tc_start_inherited"] is True
    assert out["audio_config_code"] == "8T07"
    # timeline_segments defaults to empty list
    assert out["timeline_segments"] == []


def test_qc_expected_item_own_tc_overrides_template(db, tenant_id):
    t = DeliveryTemplate(
        tenant_id=tenant_id,
        code="QC-Y",
        name="QC2",
        default_tc_start="00:59:59:00",
    )
    db.add(t)
    db.flush()

    di = DeliveryItem(
        tenant_id=tenant_id,
        delivery_template_id=t.id,
        name="D2",
        tc_start="01:00:00:00",  # item-level overrides template
        audio_config_code="ST",
    )
    db.add(di)
    db.flush()

    class _Stub:
        delivery_item_id = di.id

    out = qc_expected_for_deliverable(db, _Stub())
    assert out["tc_start"] == "01:00:00:00"
    assert out["tc_start_inherited"] is False
    assert out["audio_config_code"] == "ST"


def test_qc_expected_none_when_unlinked(db, tenant_id):
    class _Stub:
        delivery_item_id = None

    assert qc_expected_for_deliverable(db, _Stub()) is None


def test_qc_expected_none_when_item_missing(db, tenant_id):
    class _Stub:
        delivery_item_id = 99999  # non-existent

    assert qc_expected_for_deliverable(db, _Stub()) is None
