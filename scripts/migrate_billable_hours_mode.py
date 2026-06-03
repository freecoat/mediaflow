"""Migrazione v3.5.0-alpha.172.179 — Policy ore fatturabili per-booking.

Aggiunge a `bookings`:
  - billable_hours_mode        VARCHAR(16) NOT NULL DEFAULT 'max'
  - billable_hours_resource_id INTEGER NULL  (FK resources.id)
  - billable_hours_manual      FLOAT NULL

Idempotente: ALTER TABLE solo se la colonna manca. Backfill 'max' implicito
dal DEFAULT (= comportamento storico, override umana max). Nessun dato esistente
modificato nei valori.

Uso:  python scripts/migrate_billable_hours_mode.py
"""
import sys
from sqlalchemy import inspect, text

# Consenti import app.* eseguendo dalla root del progetto
sys.path.insert(0, ".")
from app.database import engine  # noqa: E402


COLUMNS = [
    ("billable_hours_mode", "VARCHAR(16) NOT NULL DEFAULT 'max'"),
    ("billable_hours_resource_id", "INTEGER NULL REFERENCES resources(id)"),
    ("billable_hours_manual", "FLOAT NULL"),
]


def migrate() -> None:
    insp = inspect(engine)
    if "bookings" not in insp.get_table_names():
        print("[migrate] tabella 'bookings' assente — niente da fare.")
        return
    existing = {c["name"] for c in insp.get_columns("bookings")}
    added = 0
    with engine.begin() as conn:
        for col, ddl in COLUMNS:
            if col not in existing:
                print(f"[migrate] ADD COLUMN bookings.{col}")
                conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {ddl}"))
                added += 1
            else:
                print(f"[migrate] bookings.{col} già presente — skip")
    print(f"[migrate] completato ({added} colonne aggiunte).")


if __name__ == "__main__":
    migrate()
