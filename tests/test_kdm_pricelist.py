"""
TDD test — Task 16: voci listino KDM (20€) + DKDM (300€).

NOTE: PriceItem ha `price_list` (non `list_price`).
PriceItem NON ha campo `code`: unicità per `name`.
"""
from app.database import SessionLocal, create_tables
from app.models import PriceItem
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
