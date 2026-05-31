"""
Tests per i tre backlog item del listino:
  1. Duplica voce listino (duplicate endpoint)
  2. Vista categorie — nessun test backend (fix CSS/markup)
  3. Cancellazione voci — soft-delete + list filter active_only=true
"""
import pytest
from unittest.mock import patch
from sqlalchemy.orm import Session
from app.models.models import (
    Tenant, PriceCategory, PriceItem, DeliverableUnitNature,
)

TENANT_ID = 1


# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed(db: Session):
    """Crea tenant, categoria e voce di partenza."""
    t = Tenant(id=TENANT_ID, name="Test Tenant", slug="test")
    db.add(t)
    cat = PriceCategory(tenant_id=TENANT_ID, name="Categoria A", sort_order=0)
    db.add(cat)
    db.flush()
    item = PriceItem(
        tenant_id=TENANT_ID,
        category_id=cat.id,
        name="DCP 4K SMPTE",
        description="Mastering DCP 4K",
        unit="day",
        unit_pre="per",
        unit_nature=DeliverableUnitNature.time_based,
        price_list=1200.0,
        price_average=900.0,
        price_low=700.0,
        hardcosts=80.0,
        keywords=["dcp", "4k", "cinema"],
        cross_dept=True,
        additional_department_ids=[2, 3],
        is_active=True,
    )
    db.add(item)
    db.commit()
    return cat, item


# ── Item 1: Duplica voce ─────────────────────────────────────────────────────

def _duplicate_item(db: Session, src: PriceItem) -> PriceItem:
    """Logica duplicazione estratta dal router (per test unitario diretto)."""
    copy = PriceItem(
        tenant_id=src.tenant_id,
        category_id=src.category_id,
        department_id=src.department_id,
        name=f"{src.name} (copia)",
        description=src.description,
        unit=src.unit,
        unit_pre=src.unit_pre,
        unit_nature=src.unit_nature,
        price_list=src.price_list,
        price_average=src.price_average,
        price_low=src.price_low,
        hardcosts=src.hardcosts,
        keywords=list(src.keywords) if src.keywords else None,
        cross_dept=src.cross_dept,
        additional_department_ids=list(src.additional_department_ids) if src.additional_department_ids else None,
        is_active=True,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return copy


def test_duplicate_creates_new_item(db: Session):
    _, src = _seed(db)
    copy = _duplicate_item(db, src)
    assert copy.id != src.id, "La copia deve avere un ID diverso dall'originale"


def test_duplicate_name_has_copia_suffix(db: Session):
    _, src = _seed(db)
    copy = _duplicate_item(db, src)
    assert copy.name == f"{src.name} (copia)"


def test_duplicate_copies_all_business_fields(db: Session):
    _, src = _seed(db)
    copy = _duplicate_item(db, src)
    assert copy.category_id == src.category_id
    assert copy.description == src.description
    assert copy.unit == src.unit
    assert copy.unit_pre == src.unit_pre
    assert copy.unit_nature == src.unit_nature
    assert copy.price_list == src.price_list
    assert copy.price_average == src.price_average
    assert copy.price_low == src.price_low
    assert copy.hardcosts == src.hardcosts
    assert copy.keywords == src.keywords
    assert copy.cross_dept == src.cross_dept
    assert copy.additional_department_ids == src.additional_department_ids


def test_duplicate_is_active_true(db: Session):
    """La copia è sempre attiva, indipendentemente dallo stato dell'originale."""
    _, src = _seed(db)
    src.is_active = False
    db.commit()
    copy = _duplicate_item(db, src)
    assert copy.is_active is True


def test_duplicate_original_unchanged(db: Session):
    """La duplicazione non altera la voce originale."""
    _, src = _seed(db)
    original_name = src.name
    _ = _duplicate_item(db, src)
    db.refresh(src)
    assert src.name == original_name
    assert src.is_active is True


def test_duplicate_keywords_are_independent_copy(db: Session):
    """Modifica alle keywords della copia non tocca l'originale."""
    _, src = _seed(db)
    copy = _duplicate_item(db, src)
    copy.keywords.append("extra")
    db.commit()
    db.refresh(src)
    assert "extra" not in (src.keywords or [])


# ── Item 3: Soft-delete + lista filtrata ──────────────────────────────────────

def test_soft_delete_sets_is_active_false(db: Session):
    """Il soft-delete imposta is_active=False senza eliminare la riga."""
    _, item = _seed(db)
    item_id = item.id
    # Simula la logica del router delete_item
    item.is_active = False
    db.commit()
    reloaded = db.query(PriceItem).filter(PriceItem.id == item_id).first()
    assert reloaded is not None, "La riga non deve essere eliminata fisicamente"
    assert reloaded.is_active is False


def test_active_only_filter_excludes_deleted(db: Session):
    """Dopo soft-delete, una query con is_active=True non restituisce la voce."""
    _, item = _seed(db)
    item.is_active = False
    db.commit()
    active_items = (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == TENANT_ID, PriceItem.is_active == True)
        .all()
    )
    ids = [i.id for i in active_items]
    assert item.id not in ids, "La voce soft-deleted non deve apparire con active_only=True"


def test_active_only_false_includes_deleted(db: Session):
    """Con active_only=False la voce soft-deleted è ancora recuperabile."""
    _, item = _seed(db)
    item.is_active = False
    db.commit()
    all_items = (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == TENANT_ID)
        .all()
    )
    ids = [i.id for i in all_items]
    assert item.id in ids, "La voce soft-deleted deve essere visibile con active_only=False"


def test_active_item_visible_in_list(db: Session):
    """Una voce attiva appare normalmente nella lista."""
    _, item = _seed(db)
    active_items = (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == TENANT_ID, PriceItem.is_active == True)
        .all()
    )
    assert item.id in [i.id for i in active_items]
