"""v3.5.0-alpha.172.206 — Unificazione link deliverable↔asset (audit B).

1. Aggiunge deliverable_assets.tenant_id (idempotente) + backfill dal
   JobDeliverable parent.
2. Reconcile: per ogni JobDeliverable con un FK primario (digital_asset_id /
   physical_asset_id) ma SENZA riga pivot corrispondente, crea la riga pivot
   mancante (source='manual', legacy). Poi risincronizza i FK primari dal pivot
   via _resync_primary (la fonte di verità diventa il pivot).

Idempotente. Eseguire una volta dopo il deploy:
    python scripts/migrate_deliverable_asset_unify.py
La parte (1) gira anche al boot (_auto_migrate_columns) per sicurezza.
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine


def add_tenant_column(engine: Engine) -> bool:
    """Aggiunge deliverable_assets.tenant_id + backfill dal parent. Ritorna True
    se ha agito."""
    insp = inspect(engine)
    if "deliverable_assets" not in insp.get_table_names():
        return False
    cols = {c["name"] for c in insp.get_columns("deliverable_assets")}
    if "tenant_id" in cols:
        return False
    with engine.begin() as cn:
        cn.execute(text(
            "ALTER TABLE deliverable_assets ADD COLUMN tenant_id INTEGER NOT NULL "
            "DEFAULT 1 REFERENCES tenants(id)"))
        # Backfill dal parent JobDeliverable
        cn.execute(text(
            "UPDATE deliverable_assets SET tenant_id = ("
            "  SELECT jd.tenant_id FROM job_deliverables jd "
            "  WHERE jd.id = deliverable_assets.job_deliverable_id) "
            "WHERE EXISTS ("
            "  SELECT 1 FROM job_deliverables jd "
            "  WHERE jd.id = deliverable_assets.job_deliverable_id)"))
    return True


def reconcile(engine) -> dict:
    """Crea pivot mancanti per i FK primari legacy + risincronizza i primari."""
    from app.database import SessionLocal
    from app.models.models import JobDeliverable, DeliverableAsset
    from app.services.deliverable_assets import link_asset, _resync_primary
    db = SessionLocal()
    counts = {"pivot_created": 0, "resynced": 0, "scanned": 0}
    try:
        delivs = db.query(JobDeliverable).all()
        for d in delivs:
            counts["scanned"] += 1
            existing = {
                (r.asset_id, r.physical_asset_id)
                for r in db.query(DeliverableAsset).filter(
                    DeliverableAsset.job_deliverable_id == d.id).all()
            }
            # FK primario digitale senza pivot → crea
            if d.digital_asset_id is not None and \
               not any(a == d.digital_asset_id for (a, _p) in existing):
                link_asset(db, d, asset_id=d.digital_asset_id, source="manual")
                counts["pivot_created"] += 1
            if d.physical_asset_id is not None and \
               not any(p == d.physical_asset_id for (_a, p) in existing):
                link_asset(db, d, physical_asset_id=d.physical_asset_id, source="manual")
                counts["pivot_created"] += 1
            # Risincronizza sempre i primari dal pivot (fonte di verità)
            _resync_primary(db, d)
            counts["resynced"] += 1
        db.commit()
    finally:
        db.close()
    return counts


def migrate(engine) -> dict:
    added = add_tenant_column(engine)
    rec = reconcile(engine)
    return {"tenant_column_added": added, **rec}


if __name__ == "__main__":
    from app.database import engine
    result = migrate(engine)
    print("[migrate_deliverable_asset_unify]", result)
