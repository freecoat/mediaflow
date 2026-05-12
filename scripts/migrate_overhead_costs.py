"""
MediaFlow — migrate_overhead_costs.py (v3.5.0-alpha.87)

Sprint S8 — Pozzo costi generici / Spese aziendali.

Crea tabella `overhead_costs` + aggiunge `tenants.capex_threshold_eur`.
Idempotente: skip se già presente. Backfill opzionale da modelli esistenti
(LossEntry restano canonici per write-off; PhysicalAsset.unit_cost feeds CAPEX).

Usage:
    .venv/Scripts/python.exe scripts/migrate_overhead_costs.py [--backfill]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text, inspect

from app.database import engine


def ensure_capex_threshold_column():
    """ALTER TABLE tenants ADD COLUMN capex_threshold_eur (idempotente)."""
    insp = inspect(engine)
    if "tenants" not in insp.get_table_names():
        print("[skip] tabella tenants non esiste")
        return
    cols = {c["name"] for c in insp.get_columns("tenants")}
    if "capex_threshold_eur" in cols:
        print("[ok] tenants.capex_threshold_eur già presente")
        return
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE tenants ADD COLUMN capex_threshold_eur FLOAT NOT NULL DEFAULT 500.0"
        ))
    print("[+] tenants.capex_threshold_eur aggiunto (default 500€)")


def ensure_overhead_costs_table():
    """Crea overhead_costs table via SQLAlchemy se mancante."""
    from app.models.models import Base, OverheadCost  # noqa
    insp = inspect(engine)
    if "overhead_costs" in insp.get_table_names():
        print("[ok] tabella overhead_costs già presente")
        return
    Base.metadata.tables["overhead_costs"].create(bind=engine)
    print("[+] tabella overhead_costs creata")


def backfill_from_physical_assets():
    """v3.5.0-alpha.87 — Crea OverheadCost retro per PhysicalAsset con
    unit_cost > tenant.capex_threshold_eur. category=capex, is_capex=True."""
    from app.database import SessionLocal
    from app.models.models import OverheadCost, PhysicalAsset, Tenant, OverheadCostCategory
    from datetime import datetime
    db = SessionLocal()
    try:
        # Map tenant_id -> threshold
        tenants = {t.id: t.capex_threshold_eur or 500.0 for t in db.query(Tenant).all()}
        if not tenants:
            print("[skip] nessun tenant trovato")
            return
        # PhysicalAsset esistenti senza OverheadCost linkata
        seq_by_year: dict[int, int] = {}
        # Pre-popola max progressivo esistente
        for code, in db.execute(text("SELECT code FROM overhead_costs WHERE code LIKE 'OH-%'")):
            try:
                _, y, n = code.split("-")
                seq_by_year[int(y)] = max(seq_by_year.get(int(y), 0), int(n))
            except Exception:
                pass
        backfilled = 0
        rows = db.query(PhysicalAsset).filter(PhysicalAsset.unit_cost.isnot(None)).all()
        for pa in rows:
            threshold = tenants.get(pa.tenant_id, 500.0)
            if (pa.unit_cost or 0) <= threshold:
                continue
            # Skip se già esiste OverheadCost linked
            exists = db.query(OverheadCost).filter(
                OverheadCost.physical_asset_id == pa.id
            ).first()
            if exists:
                continue
            year = (pa.created_at.year if pa.created_at else datetime.utcnow().year)
            seq_by_year[year] = seq_by_year.get(year, 0) + 1
            code = f"OH-{year}-{seq_by_year[year]:04d}"
            oc = OverheadCost(
                tenant_id=pa.tenant_id,
                code=code,
                category=OverheadCostCategory.capex,
                title=f"CAPEX — {pa.label or pa.kind.value}",
                description=f"Acquisto {pa.kind.value} #{pa.id}, costo unitario sopra soglia tenant",
                amount_net=pa.unit_cost or 0,
                vat_rate=22.0,
                amount_vat=round((pa.unit_cost or 0) * 0.22, 2),
                amount_total=round((pa.unit_cost or 0) * 1.22, 2),
                cost_date=(pa.created_at.date() if pa.created_at else datetime.utcnow().date()),
                is_capex=True,
                useful_life_months=36,
                amortization_method="linear",
                asset_acquisition_date=(pa.created_at.date() if pa.created_at else None),
                physical_asset_id=pa.id,
                notes="Backfill da migrate_overhead_costs.py",
            )
            db.add(oc)
            backfilled += 1
            if backfilled % 100 == 0:
                db.commit()
        db.commit()
        print(f"[+] backfill PhysicalAsset -> OverheadCost capex: {backfilled} record")
    finally:
        db.close()


def backfill_from_supplier_invoices():
    """SupplierInvoice senza project_id e job_id sono overhead. Crea
    OverheadCost (categoria=other, da rivedere manualmente)."""
    from app.database import SessionLocal
    from app.models.models import OverheadCost, SupplierInvoice, OverheadCostCategory
    from datetime import datetime
    db = SessionLocal()
    try:
        seq_by_year: dict[int, int] = {}
        for code, in db.execute(text("SELECT code FROM overhead_costs WHERE code LIKE 'OH-%'")):
            try:
                _, y, n = code.split("-")
                seq_by_year[int(y)] = max(seq_by_year.get(int(y), 0), int(n))
            except Exception:
                pass
        rows = db.query(SupplierInvoice).filter(
            SupplierInvoice.project_id.is_(None),
            SupplierInvoice.job_id.is_(None),
            SupplierInvoice.deleted_at.is_(None),
        ).all()
        backfilled = 0
        for si in rows:
            exists = db.query(OverheadCost).filter(
                OverheadCost.supplier_invoice_id == si.id
            ).first()
            if exists:
                continue
            year = si.issue_date.year if si.issue_date else datetime.utcnow().year
            seq_by_year[year] = seq_by_year.get(year, 0) + 1
            code = f"OH-{year}-{seq_by_year[year]:04d}"
            oc = OverheadCost(
                tenant_id=si.tenant_id,
                code=code,
                category=OverheadCostCategory.other,
                title=f"Fattura passiva {si.number}",
                description=f"Backfill da SupplierInvoice senza project/job",
                amount_net=si.amount_net or 0,
                vat_rate=si.vat_rate or 22.0,
                amount_vat=si.amount_vat or 0,
                amount_total=si.amount_total or 0,
                cost_date=si.issue_date,
                supplier_id=si.supplier_id,
                supplier_invoice_id=si.id,
                notes="Backfill — rivedi categoria manualmente",
            )
            db.add(oc)
            backfilled += 1
            if backfilled % 100 == 0:
                db.commit()
        db.commit()
        print(f"[+] backfill SupplierInvoice (overhead pure) -> OverheadCost: {backfilled} record")
    finally:
        db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", action="store_true",
                   help="Backfill da PhysicalAsset + SupplierInvoice senza project/job")
    args = p.parse_args()

    print("=== Migration OverheadCost ===")
    ensure_capex_threshold_column()
    ensure_overhead_costs_table()
    if args.backfill:
        print()
        print("=== Backfill ===")
        backfill_from_physical_assets()
        backfill_from_supplier_invoices()
    print()
    print("Done.")


if __name__ == "__main__":
    main()
