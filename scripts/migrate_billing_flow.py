"""
MediaFlow — migrazione v3.5.0-alpha.46: flow Cost Report → Billing.

Estende `job_cost_lines` con campi billing_status / billing_batch_id /
billed_amount, e crea le nuove tabelle:
  - billing_batches
  - billing_batch_lines
  - loss_entries

Idempotente: ALTER TABLE solo se colonna mancante, CREATE TABLE solo se
non esistente. Le tabelle nuove sono comunque create automaticamente da
`Base.metadata.create_all()` al boot tramite `create_tables()`.

Esegui:
  python scripts/migrate_billing_flow.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine, create_tables


def column_exists(table: str, column: str) -> bool:
    if table not in inspect(engine).get_table_names():
        return False
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def table_exists(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def migrate():
    print("▸ MediaFlow · migrazione billing flow (v3.5.0-alpha.46)")
    print("─" * 60)

    # 1. Crea tabelle nuove via Base.metadata.create_all (no-op per
    #    quelle esistenti, crea billing_batches/batch_lines/loss_entries)
    print("▸ create_tables() (idempotente)")
    create_tables()

    expected_tables = ["billing_batches", "billing_batch_lines", "loss_entries"]
    for t in expected_tables:
        if table_exists(t):
            print(f"  ✓ {t} presente")
        else:
            print(f"  ⚠ {t} NON creata — controllare i modelli")

    # 2. Estendi job_cost_lines
    print("▸ ALTER TABLE job_cost_lines (campi billing)")
    db = SessionLocal()
    try:
        jcl_alter = [
            ("billing_status",   "VARCHAR(16) NOT NULL DEFAULT 'not_billed'"),
            ("billing_batch_id", "INTEGER NULL REFERENCES billing_batches(id)"),
            ("billed_amount",    "REAL NULL"),
        ]
        for col, ddl in jcl_alter:
            if column_exists("job_cost_lines", col):
                print(f"  ✓ job_cost_lines.{col} già presente")
            else:
                print(f"  ▸ ADD COLUMN job_cost_lines.{col}")
                db.execute(text(f"ALTER TABLE job_cost_lines ADD COLUMN {col} {ddl}"))
        db.commit()

        print("─" * 60)
        print("Migrazione completata.")
        print("Le JobCostLine esistenti hanno billing_status='not_billed' (default).")
        print("Niente API/UI in questo step (α.46): solo schema DB.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
