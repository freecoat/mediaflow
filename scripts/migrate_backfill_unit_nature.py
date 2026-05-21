"""v3.5.0-alpha.172.19 — Backfill unit_nature su PriceItem + JobDeliverable.

Storia:
- α.172.1 (Sprint 1) ha aggiunto colonna `unit_nature` con default
  `deliverable_qty` su TUTTI i record esistenti.
- α.172.8 (Sprint 4 T5) ha corretto create/update PriceItem per derivare
  `unit_nature` dal mapping `unit → nature` (cost_line_sync.unit_nature_for).
- α.172.14 ha corretto spawn rule deliverable per nature (volume/forfait
  aggregati in 1 row, qty discreti in N row).

Bug residuo:
- PriceItem creati prima di α.172.8 hanno unit_nature='deliverable_qty'
  anche per unit=hr/day/TB/GB/allow/lump → mostrati come "Consegna · Qty"
  nel listino invece di "Lavorazione" / "Consegna · Volume".
- JobDeliverable spawnati prima di α.172.14 hanno spesso N row per volume/
  forfait (es. 100 TB → 100 row qty_planned=1 invece di 1 row qty=100).
- Deliverable orfani (quote_line_id punta a QL eliminata): residui di Bug B
  α.172.18 che non cascadeava JobDeliverable al delete.

Questo script applica 4 fix idempotenti:
1. `backfill_price_items()`: ricalcola PriceItem.unit_nature dal unit
2. `backfill_deliverables()`: ricalcola JobDeliverable.unit_nature dal unit
3. `consolidate_volume_forfait_deliverables()`: collassa N row → 1 row per
   QL con nature volume/manual_allow (sum quantity_planned + delivered)
4. `delete_orphan_deliverables()`: hard-delete Deliverable con quote_line_id
   inesistente E senza booking link E senza asset (safe orphans).

Le funzioni 1+2 sono auto-runned silently al boot in app/main.py lifespan.
3+4 sono manuali (potenzialmente distruttive su data).

Uso CLI:
  python -m scripts.migrate_backfill_unit_nature             # 1+2 (safe)
  python -m scripts.migrate_backfill_unit_nature --all       # 1+2+3+4
  python -m scripts.migrate_backfill_unit_nature --consolidate
  python -m scripts.migrate_backfill_unit_nature --orphans
"""
from __future__ import annotations

import argparse
from typing import Tuple

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    PriceItem, JobDeliverable, DeliverableUnitNature, DeliverableBillingStatus,
)
from app.services.cost_line_sync import unit_nature_for


def backfill_price_items(db: Session) -> int:
    """Aggiorna PriceItem.unit_nature dal mapping `unit_nature_for(unit)`.

    Ritorna numero di righe modificate.
    """
    n = 0
    for pi in db.query(PriceItem).all():
        expected = unit_nature_for(pi.unit)
        current = pi.unit_nature.value if hasattr(pi.unit_nature, "value") else str(pi.unit_nature or "")
        if current != expected:
            pi.unit_nature = DeliverableUnitNature(expected)
            n += 1
    if n:
        db.flush()
    return n


def backfill_deliverables(db: Session) -> int:
    """Aggiorna JobDeliverable.unit_nature dal mapping. Idempotente."""
    n = 0
    for d in db.query(JobDeliverable).all():
        expected = unit_nature_for(d.unit)
        current = d.unit_nature.value if hasattr(d.unit_nature, "value") else str(d.unit_nature or "")
        if current != expected:
            d.unit_nature = DeliverableUnitNature(expected)
            n += 1
    if n:
        db.flush()
    return n


def consolidate_volume_forfait_deliverables(db: Session) -> Tuple[int, int]:
    """Collassa Deliverable multi-row per QL con nature volume/manual_allow.

    Spawn rule α.172.14: queste nature devono avere 1 row aggregato.
    Pre-α.172.14 spawn creava N row. Questo le consolida.

    Strategia per ogni gruppo (quote_line_id, unit) con count > 1:
    - Tieni la prima row (id più piccolo)
    - Somma quantity_planned + quantity_delivered + total_quoted + total_accrued
    - Mantieni primo confirmed_at (se presente in qualche row)
    - Mantieni primo digital_asset_id / physical_asset_id
    - billing_status = max severity (paid > billed > in_batch > not_billed)
    - Cancella le restanti (db.delete)

    BLOCK se qualche row ha billing_status != not_billed (per safety: rows
    già fatturate non si consolidano).

    Ritorna (groups_consolidated, rows_deleted).
    """
    from sqlalchemy import func
    # Trova gruppi candidati: stessa QL+unit, count>1, nature non-deliverable_qty
    groups = (
        db.query(
            JobDeliverable.quote_line_id,
            JobDeliverable.unit,
            func.count(JobDeliverable.id).label("cnt"),
        )
        .filter(
            JobDeliverable.quote_line_id.isnot(None),
            JobDeliverable.unit_nature.in_([
                DeliverableUnitNature.deliverable_volume,
                DeliverableUnitNature.manual_allow,
            ]),
        )
        .group_by(JobDeliverable.quote_line_id, JobDeliverable.unit)
        .having(func.count(JobDeliverable.id) > 1)
        .all()
    )
    groups_consolidated = 0
    rows_deleted = 0
    for ql_id, unit, cnt in groups:
        rows = (
            db.query(JobDeliverable)
            .filter(
                JobDeliverable.quote_line_id == ql_id,
                JobDeliverable.unit == unit,
            )
            .order_by(JobDeliverable.id.asc())
            .all()
        )
        # Skip se qualcuno è già fatturato
        if any(r.billing_status != DeliverableBillingStatus.not_billed for r in rows):
            print(f"  SKIP QL#{ql_id} unit={unit}: {len(rows)} row, almeno una billed/in_batch")
            continue
        head = rows[0]
        tail = rows[1:]
        # Aggrega
        head.quantity_planned = sum((r.quantity_planned or 0.0) for r in rows)
        head.quantity_delivered = sum((r.quantity_delivered or 0.0) for r in rows)
        head.total_quoted = round((head.quantity_planned or 0.0) * (head.unit_price or 0.0), 2)
        head.total_accrued = sum((r.total_accrued or 0.0) for r in rows)
        head.total_cost_accrued = sum((r.total_cost_accrued or 0.0) for r in rows)
        # confirmed_at: usa primo non-NULL
        for r in tail:
            if r.confirmed_at and not head.confirmed_at:
                head.confirmed_at = r.confirmed_at
                head.confirmed_by_user_id = r.confirmed_by_user_id
            if r.digital_asset_id and not head.digital_asset_id:
                head.digital_asset_id = r.digital_asset_id
            if r.physical_asset_id and not head.physical_asset_id:
                head.physical_asset_id = r.physical_asset_id
        # Delete tail
        for r in tail:
            db.delete(r)
        rows_deleted += len(tail)
        groups_consolidated += 1
        print(f"  OK QL#{ql_id} unit={unit}: collassati {len(rows)} -> 1 (qty={head.quantity_planned})")
    if rows_deleted:
        db.flush()
    return groups_consolidated, rows_deleted


def delete_orphan_deliverables(db: Session, *, dry_run: bool = False) -> int:
    """Hard-delete Deliverable con `quote_line_id` non esistente.

    SAFE: skip se Deliverable ha digital_asset_id, physical_asset_id, o
    confirmed_at valorizzati (potenziale lavoro perso).

    Ritorna conteggio cancellati (o conteggio candidati se dry_run).
    """
    from app.models import QuoteLine
    candidates = (
        db.query(JobDeliverable)
        .outerjoin(QuoteLine, JobDeliverable.quote_line_id == QuoteLine.id)
        .filter(
            JobDeliverable.quote_line_id.isnot(None),
            QuoteLine.id.is_(None),
            JobDeliverable.digital_asset_id.is_(None),
            JobDeliverable.physical_asset_id.is_(None),
            JobDeliverable.confirmed_at.is_(None),
        )
        .all()
    )
    if dry_run:
        return len(candidates)
    for d in candidates:
        db.delete(d)
    if candidates:
        db.flush()
    return len(candidates)


def run_silent_backfill(db: Session) -> dict:
    """Versione safe per boot lifespan: solo 1+2 (no consolidate, no orphan).

    Idempotente. Non commit (caller fa).
    """
    n_pi = backfill_price_items(db)
    n_dlv = backfill_deliverables(db)
    return {"price_items_fixed": n_pi, "deliverables_fixed": n_dlv}


def main():
    ap = argparse.ArgumentParser(description="Backfill unit_nature MediaFlow")
    ap.add_argument("--all", action="store_true", help="Esegue tutti i 4 step (anche consolidate + orphans)")
    ap.add_argument("--consolidate", action="store_true", help="Esegue solo consolidate volume/forfait")
    ap.add_argument("--orphans", action="store_true", help="Hard-delete deliverable orfani")
    ap.add_argument("--dry-run", action="store_true", help="Conta solo, non modifica")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        print("== Step 1+2: backfill unit_nature ==")
        n_pi = backfill_price_items(db)
        n_dlv = backfill_deliverables(db)
        print(f"  PriceItem aggiornati: {n_pi}")
        print(f"  Deliverable aggiornati: {n_dlv}")
        if args.all or args.consolidate:
            print()
            print("== Step 3: consolidate multi-row volume/forfait ==")
            g, r = consolidate_volume_forfait_deliverables(db)
            print(f"  Gruppi collassati: {g}, row cancellate: {r}")
        if args.all or args.orphans:
            print()
            print("== Step 4: delete orphan deliverables ==")
            if args.dry_run:
                cnt = delete_orphan_deliverables(db, dry_run=True)
                print(f"  Candidati cancellabili: {cnt} (dry-run)")
            else:
                cnt = delete_orphan_deliverables(db)
                print(f"  Cancellati: {cnt}")
        if args.dry_run:
            print()
            print("[dry-run] rollback")
            db.rollback()
        else:
            db.commit()
            print()
            print("✓ Commit OK")
    except Exception as e:
        db.rollback()
        print(f"✗ Errore: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
