"""v3.5.0-alpha.172.161 — Backfill retroattivo: lega i JobDeliverable esistenti
all'item di capitolato (DeliveryItem) da cui derivano, popolando
``delivery_item_id`` (e ``QuoteLine.delivery_item_id``) dove oggi è NULL.

Prima di α.172.161 la catena capitolato→quote→job NON persisteva il FK
strutturato: la riga di quote conservava solo ``price_item_id`` (voce-listino),
``section_label`` (broadcaster) e ``detail`` (nome/i item capitolato come stringa).
Questo script ricostruisce il link by-name in modo conservativo.

Algoritmo per deliverable (delivery_item_id IS NULL, con quote_line + section_label):
  1. broadcaster = quote_line.section_label
  2. template = DeliveryTemplate del tenant con broadcaster (o name) corrispondente
  3. candidati = DeliveryItem(template) con suggested_price_item_id == line.price_item_id
  4. 1 candidato            -> match
     >1 candidati           -> disambigua: item.name presente in line.detail; se 1 -> match
     0 candidati / ambiguo  -> skip (resta selezionabile a mano in planning)

Idempotente: tocca solo righe con delivery_item_id NULL. Sicuro da rilanciare.

Uso:
    python scripts/backfill_deliverable_capitolato_link.py            # esegue
    python scripts/backfill_deliverable_capitolato_link.py --dry-run  # solo report
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.database import SessionLocal
from app.models import (
    JobDeliverable, QuoteLine, DeliveryTemplate, DeliveryItem,
)


def _norm(s):
    return (s or "").strip().lower()


def _match_template(db, tenant_id, broadcaster):
    """Trova il template per broadcaster (poi name) — attivo, del tenant."""
    if not broadcaster:
        return None
    bc = _norm(broadcaster)
    rows = db.execute(
        select(DeliveryTemplate).where(DeliveryTemplate.tenant_id == tenant_id)
    ).scalars().all()
    # match esatto su broadcaster, poi su name, poi "contiene"
    for t in rows:
        if _norm(t.broadcaster) == bc:
            return t
    for t in rows:
        if _norm(t.name) == bc:
            return t
    for t in rows:
        if bc and (bc in _norm(t.broadcaster) or _norm(t.broadcaster) in bc):
            return t
    return None


def backfill(dry_run: bool = False, db=None):
    own = db is None
    if own:
        db = SessionLocal()
    stats = {"scanned": 0, "linked": 0, "skip_no_line": 0, "skip_no_label": 0,
             "skip_no_template": 0, "skip_no_candidate": 0, "skip_ambiguous": 0}
    try:
        delivs = db.execute(
            select(JobDeliverable).where(
                JobDeliverable.delivery_item_id.is_(None),
                JobDeliverable.deleted_at.is_(None),
            )
        ).scalars().all()
        for d in delivs:
            stats["scanned"] += 1
            if not d.quote_line_id:
                stats["skip_no_line"] += 1
                continue
            line = db.get(QuoteLine, d.quote_line_id)
            if not line:
                stats["skip_no_line"] += 1
                continue
            if not line.section_label:
                stats["skip_no_label"] += 1
                continue
            tpl = _match_template(db, d.tenant_id, line.section_label)
            if not tpl:
                stats["skip_no_template"] += 1
                continue
            cands = db.execute(
                select(DeliveryItem).where(
                    DeliveryItem.delivery_template_id == tpl.id,
                    DeliveryItem.tenant_id == d.tenant_id,
                    DeliveryItem.is_active == True,  # noqa: E712
                    DeliveryItem.suggested_price_item_id == line.price_item_id,
                )
            ).scalars().all()
            chosen = None
            if len(cands) == 1:
                chosen = cands[0]
            elif len(cands) > 1:
                detail = _norm(line.detail)
                hits = [c for c in cands if _norm(c.name) and _norm(c.name) in detail]
                if len(hits) == 1:
                    chosen = hits[0]
                else:
                    stats["skip_ambiguous"] += 1
                    continue
            else:
                stats["skip_no_candidate"] += 1
                continue
            # match trovato
            print(f"  [LINK] deliverable #{d.id} '{d.name}' -> DeliveryItem #{chosen.id} "
                  f"'{chosen.name}' (tpl {tpl.code}/{tpl.broadcaster})")
            if not dry_run:
                d.delivery_item_id = chosen.id
                if line.delivery_item_id is None:
                    line.delivery_item_id = chosen.id
            stats["linked"] += 1
        if not dry_run:
            db.commit()
    finally:
        if own:
            db.close()
    print("\n=== Backfill capitolato link ===")
    for k, v in stats.items():
        print(f"  {k:20s}: {v}")
    if dry_run:
        print("  (dry-run: nessuna modifica scritta)")
    return stats


if __name__ == "__main__":
    backfill(dry_run="--dry-run" in sys.argv)
