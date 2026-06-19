"""
TDD test — Task 16: voci listino KDM (20€) + DKDM (300€).

NOTE: PriceItem ha `price_list` (non `list_price`).
PriceItem NON ha campo `code`: unicità per `name`.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import SessionLocal, create_tables
from app.models import PriceItem
from app.models.models import Base, Tenant
from app.services.kdm_pricing import ensure_kdm_price_items, KDM_NAME, DKDM_NAME


def test_ensure_creates_kdm_dkdm_idempotent():
    create_tables()
    db = SessionLocal()
    try:
        ensure_kdm_price_items(db)
        ensure_kdm_price_items(db)  # idempotente: nessun duplicato

        kdm = db.query(PriceItem).filter(
            PriceItem.name == KDM_NAME,
            PriceItem.tenant_id == 1
        ).all()
        dkdm = db.query(PriceItem).filter(
            PriceItem.name == DKDM_NAME,
            PriceItem.tenant_id == 1
        ).all()

        assert len(kdm) == 1, f"Atteso 1 voce KDM, trovato {len(kdm)}"
        assert len(dkdm) == 1, f"Atteso 1 voce DKDM, trovato {len(dkdm)}"
        assert kdm[0].price_list == 20.0, f"KDM price_list atteso 20.0, trovato {kdm[0].price_list}"
        assert dkdm[0].price_list == 300.0, f"DKDM price_list atteso 300.0, trovato {dkdm[0].price_list}"
    finally:
        db.rollback()
        db.close()


# ── Fixtures isolate per i nuovi test (in-memory) ────────────────────────────

@pytest.fixture
def _mem_db():
    """SQLite in-memory fresco con schema completo."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    # Tenant minimo richiesto da FK
    session.add(Tenant(id=1, name="Test", slug="test"))
    session.flush()
    yield session
    session.close()
    engine.dispose()


# ── Test: commit=False non commtta (rollback rimuove le righe) ───────────────

def test_commit_false_does_not_commit(_mem_db):
    """commit=False: le righe esistono in sessione ma vengono annullate da rollback.

    Verifica che ensure_kdm_price_items(..., commit=False) non chiami db.commit()
    internamente: dopo un db.rollback() le voci non devono più essere presenti.
    """
    db = _mem_db
    ensure_kdm_price_items(db, tenant_id=1, commit=False)

    # Le righe sono visibili nella sessione corrente (flush avvenuto)
    count_before = (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == 1)
        .execution_options(include_deleted=True)
        .count()
    )
    assert count_before >= 2, "flush deve rendere le righe visibili nella sessione"

    # Rollback annulla tutto — se ci fosse stato un commit intermedio
    # le righe sarebbero persistite e il count sarebbe >= 2 anche dopo.
    db.rollback()

    count_after = (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == 1)
        .execution_options(include_deleted=True)
        .count()
    )
    assert count_after == 0, (
        f"Dopo rollback dovrebbero esserci 0 righe (commit=False non deve aver "
        f"committato), trovate: {count_after}"
    )


# ── Test: voce soft-deletata viene riattivata ────────────────────────────────

def test_soft_deleted_price_item_reactivated(_mem_db):
    """Una voce KDM soft-deletata (is_active=False) viene riattivata da ensure.

    Scenario: voce presente nel DB ma con is_active=False (soft-delete).
    ensure_kdm_price_items deve riattivarla invece di saltarla, così che il
    lookup successivo in materialize_produced_kdm (filtra is_active=True) la trovi.
    """
    db = _mem_db

    # Crea la voce KDM direttamente come soft-deleted
    from app.models.models import PriceCategory
    cat = PriceCategory(tenant_id=1, name="MASTERING DCP / DCDM", sort_order=30)
    db.add(cat)
    db.flush()

    soft_deleted = PriceItem(
        tenant_id=1,
        category_id=cat.id,
        name=KDM_NAME,
        description="test",
        unit="pc",
        price_list=20.0,
        price_average=20.0,
        price_low=20.0,
        is_active=False,  # soft-deleted
    )
    db.add(soft_deleted)
    db.flush()
    item_id = soft_deleted.id

    # Verifica precondizione: voce è inattiva
    assert soft_deleted.is_active is False

    # Chiama ensure — deve riattivare la voce esistente
    ensure_kdm_price_items(db, tenant_id=1, commit=False)

    # Ricarica dalla sessione
    db.flush()
    reloaded = db.get(PriceItem, item_id)
    assert reloaded is not None
    assert reloaded.is_active is True, (
        "La voce soft-deletata deve essere riattivata da ensure_kdm_price_items"
    )

    # Non devono esserci duplicati (stesso nome)
    count = (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == 1, PriceItem.name == KDM_NAME)
        .execution_options(include_deleted=True)
        .count()
    )
    assert count == 1, f"Non devono esserci duplicati KDM, trovati: {count}"
