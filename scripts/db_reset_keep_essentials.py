"""DB reset selettivo — preserva anagrafiche, purga dati transazionali.

v3.5.0-alpha.172.42 — richiesta Matteo post-audit: ripartire da DB pulito
basato su clienti+progetti+quote attive correnti, eliminando job/booking/
fatture/acconti/anomalie/asset accumulati dai test.

PRESERVA:
- Tenant, User, Role
- Department, Resource (anagrafica)
- PriceItem (listino), PriceCategory
- DeliveryTemplate, TechSheetFieldOption
- WorkingHoursPolicy, Holiday
- Client (tutti)
- Project (NON in cestino: deleted_at IS NULL)
- Quote NON in cestino
- QuoteLine collegate alle Quote preservate

PURGA:
- Job + JobCostLine + JobResourceAssignment
- Booking + BookingAssignment + BookingChange + BookingDeliverable
- JobDeliverable + DeliverableSpec + DeliverableAsset + DeliverableBilledSlice
- TimePunch
- AdvancePayment + AdvancePaymentAllocation + AdvancePaymentConsumption
  + AdvancePaymentDeliverableAllocation + QuoteAdvanceAllocation
- Invoice + InvoiceLine + InvoicePayment
- BillingBatch + BillingBatchLine
- JCLBilledSlice
- SupplierInvoice + SupplierInvoicePayment + Supplier
- AnomalyEntry + LossEntry + OverheadCost
- Notification + AIAction + AIMessage + AIConversation
- Asset + PhysicalAsset + AssetTag + AssetMembership + AssetMovement
- ResourceUnavailability + ResourcePreset
- ProjectTechSheet + Timesheet + Expense
- VFXShot + ClientWork + ProjectMilestone + IngestBatch
- AssetTag (relation)

USO: `.venv/Scripts/python.exe scripts/db_reset_keep_essentials.py [--yes]`
Senza `--yes` chiede conferma. Con `--yes` esegue silenziosamente.
"""
from __future__ import annotations
import sys
import os
import argparse

# Add project root to sys.path so `from app.database` works when launched
# via `python scripts/db_reset_keep_essentials.py` (no -m).
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import text


# Ordine importante: child → parent per evitare FK violations
PURGE_TABLES_ORDER = [
    # AI / Notification
    "ai_actions",
    "ai_messages",
    "ai_conversations",
    "notifications",
    # Anomalie / Loss / Overhead
    "anomaly_entries",
    "loss_entries",
    "overhead_costs",
    # Asset / Physical / Movement
    "asset_movements",
    "asset_memberships",
    "asset_tags",
    "assets",
    "physical_assets",
    "ingest_batches",
    # Punches / Timesheet / Expense
    "time_punches",
    "timesheets",
    "expenses",
    # Booking
    "booking_deliverables",
    "booking_changes",
    "booking_assignments",
    "bookings",
    # Resource state
    "resource_unavailabilities",
    "resource_presets",
    # Billing slice / batch / invoice payments
    "jcl_billed_slices",
    "deliverable_billed_slices",
    "invoice_payments",
    "billing_batch_lines",
    "billing_batches",
    # Advance ledger
    "advance_payment_deliverable_allocations",
    "advance_payment_consumptions",
    "advance_payment_allocations",
    "quote_advance_allocations",
    "advance_payments",
    # Invoice
    "invoice_lines",
    "invoices",
    # Supplier
    "supplier_invoice_payments",
    "supplier_invoices",
    "suppliers",
    # Deliverable cascade
    "deliverable_assets",
    "deliverable_specs",
    "job_deliverables",
    # Project tech sheets + per-project meta
    "project_tech_sheets",
    "vfx_shots",
    "client_works",
    "project_milestones",
    # Job + cost line + assignment
    "job_resource_assignments",
    "job_cost_lines",
    "jobs",
]


def reset(yes: bool = False) -> None:
    from app.database import engine, SessionLocal
    from sqlalchemy import inspect
    insp = inspect(engine)
    existing = set(insp.get_table_names())

    db = SessionLocal()
    try:
        # Conta record pre-purge per audit
        print("Stato DB pre-purge:")
        for t in PURGE_TABLES_ORDER:
            if t in existing:
                count = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                if count:
                    print(f"  {t}: {count}")

        # Conta anagrafiche preservate
        print("\nAnagrafiche preservate:")
        for t in ("clients", "projects", "quotes", "quote_lines", "tenants",
                  "users", "roles", "departments", "resources", "price_items",
                  "delivery_templates", "working_hours_policies", "holidays"):
            if t in existing:
                count = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                print(f"  {t}: {count}")

        if not yes:
            print("\n[!] Esegui con --yes per procedere alla purga.")
            print("[!] Backup DB raccomandato prima dell'esecuzione (db_snapshots/).")
            return

        # Purga con foreign_keys OFF (SQLite) per ordine semplificato
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            for t in PURGE_TABLES_ORDER:
                if t in existing:
                    res = conn.execute(text(f"DELETE FROM {t}"))
                    if res.rowcount:
                        print(f"  [OK] {t}: purged {res.rowcount} rows")
            # Re-enable FK per integrity check
            conn.execute(text("PRAGMA foreign_keys = ON"))

        # Verifica post-purge
        print("\nStato DB post-purge:")
        for t in PURGE_TABLES_ORDER:
            if t in existing:
                count = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                if count:
                    print(f"  [!] {t}: {count} righe ancora presenti (FK violation?)")
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Salta conferma + esegui")
    args = parser.parse_args()
    reset(yes=args.yes)
