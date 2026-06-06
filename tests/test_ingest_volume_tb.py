"""
Tests per _volume_increment — logica incremento quantity_delivered su ingest MHL/CSV.

Verifica:
- deliverable_volume: incremento in TB (bytes / 1e12), arrotondato a 4 decimali
- deliverable_volume: cap a (planned - delivered) se il volume supera il rimanente
- deliverable_volume: restituisce 0 se già completamente consegnato (idempotente)
- deliverable_qty (pezzi): flat +1.0
- deliverable_qty: cap a 1 se rimane solo 0.5 piece (edge)
- deliverable_qty: restituisce 0 se già completo
"""
from unittest.mock import MagicMock
from app.routers.ingest_deliverables import _volume_increment
from app.models.models import DeliverableUnitNature


def _make_deliverable(
    unit_nature: DeliverableUnitNature,
    quantity_planned: float,
    quantity_delivered: float,
) -> MagicMock:
    d = MagicMock()
    d.unit_nature = unit_nature
    d.quantity_planned = quantity_planned
    d.quantity_delivered = quantity_delivered
    return d


# ---------------------------------------------------------------------------
# VOLUME (TB) deliverable
# ---------------------------------------------------------------------------

def test_volume_standard_increment():
    """2 TB ingest su deliverable da 10 TB → incremento 2.0"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_volume, 10.0, 0.0)
    inc = _volume_increment(d, int(2e12))  # 2 TB in bytes
    assert inc == 2.0, f"expected 2.0, got {inc}"


def test_volume_partial_bytes_rounded():
    """1.5678 TB arrotondato a 4 decimali → 1.5678"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_volume, 10.0, 0.0)
    inc = _volume_increment(d, 1_567_800_000_000)
    assert inc == round(1_567_800_000_000 / 1e12, 4)


def test_volume_cap_at_remaining():
    """8 TB ingest su deliverable da 10 TB già a 5 TB → inc cappato a 5.0"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_volume, 10.0, 5.0)
    inc = _volume_increment(d, int(8e12))
    assert inc == 5.0, f"expected 5.0, got {inc}"


def test_volume_already_full_returns_zero():
    """Deliverable già completo (10/10 TB) → incremento 0"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_volume, 10.0, 10.0)
    inc = _volume_increment(d, int(2e12))
    assert inc == 0.0, f"expected 0.0, got {inc}"


def test_volume_zero_bytes_returns_zero():
    """0 bytes → incremento 0"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_volume, 10.0, 0.0)
    inc = _volume_increment(d, 0)
    assert inc == 0.0


# ---------------------------------------------------------------------------
# PC/QTY deliverable
# ---------------------------------------------------------------------------

def test_qty_flat_increment():
    """Tipo pc, 3 pezzi pianificati, 0 consegnati → +1.0"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_qty, 3.0, 0.0)
    inc = _volume_increment(d, int(5e12))  # bytes irrilevanti
    assert inc == 1.0


def test_qty_cap_when_one_left():
    """Tipo pc, 3 pianificati, 2 consegnati → +1.0 (esattamente 1 rimane)"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_qty, 3.0, 2.0)
    inc = _volume_increment(d, int(5e12))
    assert inc == 1.0


def test_qty_already_full_returns_zero():
    """Tipo pc, 3 pianificati, 3 consegnati → 0"""
    d = _make_deliverable(DeliverableUnitNature.deliverable_qty, 3.0, 3.0)
    inc = _volume_increment(d, int(5e12))
    assert inc == 0.0


def test_time_based_treated_as_flat():
    """time_based non è volume → flat +1 logic"""
    d = _make_deliverable(DeliverableUnitNature.time_based, 5.0, 0.0)
    inc = _volume_increment(d, int(2e12))
    assert inc == 1.0


def test_manual_allow_treated_as_flat():
    """manual_allow non è volume → flat +1 logic"""
    d = _make_deliverable(DeliverableUnitNature.manual_allow, 5.0, 2.0)
    inc = _volume_increment(d, int(2e12))
    assert inc == 1.0
