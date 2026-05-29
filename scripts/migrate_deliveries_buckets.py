"""v3.5.0-alpha.172.135 (F1 pipeline deliverables) — consolidamento listino bucket.

Migrazione B (decisione spec docs/superpowers/2026-05-29-deliverables-pipeline-design.md):
1. crea/recupera categoria listino "Deliveries";
2. per ogni DeliveryItem attivo → match-or-create voce-bucket + link via
   ``suggested_price_item_id`` (decisione 9);
3. soft-delete delle vecchie ~13 voci deliverable non uniformi (categorie
   MASTERING DCP / DELIVERABLES VIDEO / DELIVERABLES SOUND). NON rimappa le
   quote-line storiche (rischio accettato, "possiamo sbagliare").

Idempotente: rilanciabile, il match per name riusa i bucket esistenti.

Uso:
    .venv/Scripts/python.exe scripts/migrate_deliveries_buckets.py --dry
    .venv/Scripts/python.exe scripts/migrate_deliveries_buckets.py
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models.models import DeliveryItem, PriceItem, PriceCategory
from app.services.delivery_bucket import compute_bucket, match_or_create_bucket

# Categorie "vecchio mondo" deliverable da soft-deprecare (per name, robusto a id).
LEGACY_CATEGORY_NAMES = {
    "MASTERING DCP / DCDM",
    "DELIVERABLES VIDEO",
    "DELIVERABLES SOUND",
}
DELIVERIES_CATEGORY = "Deliveries"


def _get_or_create_category(db, tenant_id: int, dry: bool) -> PriceCategory:
    cat = (
        db.query(PriceCategory)
        .filter(PriceCategory.tenant_id == tenant_id, PriceCategory.name == DELIVERIES_CATEGORY)
        .first()
    )
    if cat:
        return cat
    cat = PriceCategory(tenant_id=tenant_id, name=DELIVERIES_CATEGORY)
    db.add(cat)
    if not dry:
        db.flush()
    else:
        cat.id = -1  # placeholder per dry-run
    return cat


def run(dry: bool, tenant_id: int) -> None:
    db = SessionLocal()
    try:
        cat = _get_or_create_category(db, tenant_id, dry)
        items = (
            db.query(DeliveryItem)
            .filter(DeliveryItem.tenant_id == tenant_id, DeliveryItem.is_active == True)  # noqa: E712
            .all()
        )
        print(f"DeliveryItem attivi: {len(items)} | categoria '{DELIVERIES_CATEGORY}' id={cat.id}")

        bucket_counts: Counter = Counter()
        group_counts: Counter = Counter()
        linked = 0

        if dry:
            # In dry-run non scriviamo: simuliamo i bucket distinti.
            seen: dict[str, int] = {}
            for it in items:
                spec = compute_bucket(db, it)
                group_counts[spec.group] += 1
                bucket_counts[spec.label] += 1
                seen.setdefault(spec.label, 0)
                seen[spec.label] += 1
            print(f"\n=== DRY RUN — {len(seen)} bucket distinti ===")
            for label, n in bucket_counts.most_common():
                print(f"{n:4}  {label}")
            print("\nPer gruppo:", dict(group_counts))
            # Conta legacy che verrebbero soft-deleted.
            legacy = _legacy_items(db, tenant_id)
            print(f"\nVecchie voci deliverable da soft-deprecare: {len(legacy)}")
            for pi in legacy:
                print(f"  - [{pi.category.name}] {pi.name} (id={pi.id})")
            db.rollback()
            return

        for it in items:
            pi = match_or_create_bucket(db, tenant_id, it, cat.id)
            it.suggested_price_item_id = pi.id
            bucket_counts[pi.name] += 1
            linked += 1
        db.flush()

        legacy = _legacy_items(db, tenant_id)
        for pi in legacy:
            pi.is_active = False
            if not (pi.description or "").startswith("[deprecata]"):
                pi.description = f"[deprecata] sostituita dai bucket '{DELIVERIES_CATEGORY}'. " + (pi.description or "")

        db.commit()
        n_buckets = (
            db.query(PriceItem)
            .filter(PriceItem.tenant_id == tenant_id, PriceItem.category_id == cat.id,
                    PriceItem.is_active == True)  # noqa: E712
            .count()
        )
        print(f"\n[OK] Migrazione completata.")
        print(f"   - {linked} DeliveryItem linkati a {n_buckets} voci-bucket.")
        print(f"   - {len(legacy)} vecchie voci deliverable soft-deprecate.")
    finally:
        db.close()


def _legacy_items(db, tenant_id: int) -> list[PriceItem]:
    cat_ids = [
        c.id for c in db.query(PriceCategory)
        .filter(PriceCategory.tenant_id == tenant_id,
                PriceCategory.name.in_(LEGACY_CATEGORY_NAMES))
        .all()
    ]
    if not cat_ids:
        return []
    return (
        db.query(PriceItem)
        .filter(PriceItem.tenant_id == tenant_id,
                PriceItem.category_id.in_(cat_ids),
                PriceItem.is_active == True)  # noqa: E712
        .all()
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="preview senza scrivere")
    ap.add_argument("--tenant", type=int, default=1)
    args = ap.parse_args()
    run(dry=args.dry, tenant_id=args.tenant)
