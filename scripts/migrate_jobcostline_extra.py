"""
MediaFlow — migrazione: JobCostLine.is_extra

Aggiunge `is_extra BOOLEAN NOT NULL DEFAULT 0` su `job_cost_lines`. Marca le
lavorazioni "extra" aggiunte dopo l'approvazione della quote (es. il cliente
chiede un upres in più). Le lavorazioni ereditate dalla quote restano
`is_extra=False` ma possono comunque generare extra se `quantity_actual >
quantity_quoted` (sforamento monte ore).

Idempotente.

Esegui:
  python scripts/migrate_jobcostline_extra.py
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
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione is_extra su job_cost_lines")
    print("─" * 60)

    create_tables()
    db = SessionLocal()
    try:
        if not column_exists("job_cost_lines", "is_extra"):
            print("▸ ALTER TABLE job_cost_lines ADD COLUMN is_extra BOOLEAN NOT NULL DEFAULT 0")
            db.execute(text(
                "ALTER TABLE job_cost_lines ADD COLUMN is_extra BOOLEAN NOT NULL DEFAULT 0"
            ))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ is_extra già presente")

        print("─" * 60)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
