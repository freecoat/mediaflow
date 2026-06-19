"""Voci listino KDM/DKDM (idempotent upsert). Usato da seed + migrazione.

PriceItem NON ha campo `code`: unicità per `name` + `tenant_id`.
Il campo prezzo è `price_list` (non `list_price` o `unit_price`).
"""
from sqlalchemy.orm import Session

from app.models import PriceCategory, PriceItem, Department

# Nome canonico — usato come chiave idempotenza (PriceItem non ha campo `code`)
KDM_NAME = "KDM — Key Delivery Message"
DKDM_NAME = "DKDM — Distribution KDM"

# Manteniamo anche KDM_CODE/DKDM_CODE per retrocompatibilità con il brief
KDM_CODE = "KDM"
DKDM_CODE = "DKDM"

_CATEGORY_NAME = "MASTERING DCP / DCDM"

_SPECS = [
    (
        KDM_NAME,
        "Key Delivery Message per sala cinema (singolo server). Dettagliare: "
        "numero sale, validità temporale, codice TMS/server.",
        20.0,
        ["kdm", "key delivery message", "chiave cinema", "dkdm generation", "cinema server"],
    ),
    (
        DKDM_NAME,
        "Distribution KDM master per distributore (validità lunga, multi-sala). "
        "Dettagliare: distributore, numero copie, validità.",
        300.0,
        ["dkdm", "distribution kdm", "generation of dkdm", "master kdm", "distributore"],
    ),
]


def _get_or_create_category(db: Session, tenant_id: int) -> int:
    """Restituisce id della categoria MASTERING DCP / DCDM, creandola se mancante."""
    cat = (
        db.query(PriceCategory)
        .filter(
            PriceCategory.tenant_id == tenant_id,
            PriceCategory.name == _CATEGORY_NAME,
        )
        .first()
    )
    if cat:
        return cat.id
    cat = PriceCategory(
        tenant_id=tenant_id,
        name=_CATEGORY_NAME,
        description="Mastering Digital Cinema Package + Dolby Vision/Atmos",
        sort_order=30,
    )
    db.add(cat)
    db.flush()
    return cat.id


def _di_video_dept_id(db: Session, tenant_id: int):
    """Restituisce id del reparto DI-Video, o None se non esiste."""
    dept = (
        db.query(Department)
        .filter(
            Department.tenant_id == tenant_id,
            Department.code.in_(("DI-VIDEO", "DI-Video", "DI")),
        )
        .first()
    )
    return dept.id if dept else None


def ensure_kdm_price_items(db: Session, tenant_id: int = 1) -> None:
    """Crea le voci KDM/DKDM nel listino se mancanti per il tenant.

    Idempotente: controlla per `name` + `tenant_id` con include_deleted=True
    per evitare duplicati su record soft-deleted (convenzione progetto).
    """
    category_id = _get_or_create_category(db, tenant_id)
    dept_id = _di_video_dept_id(db, tenant_id)

    for name, description, price, keywords in _SPECS:
        exists = (
            db.query(PriceItem)
            .filter(PriceItem.tenant_id == tenant_id, PriceItem.name == name)
            .execution_options(include_deleted=True)
            .first()
        )
        if exists:
            continue
        pi = PriceItem(
            tenant_id=tenant_id,
            category_id=category_id,
            department_id=dept_id,
            name=name,
            description=description,
            unit_pre="per",
            unit="pc",
            price_list=price,
            price_average=price,
            price_low=price,
            keywords=keywords,
            is_active=True,
        )
        db.add(pi)

    db.commit()
