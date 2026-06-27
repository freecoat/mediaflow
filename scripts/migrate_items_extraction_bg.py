"""Migrazione non distruttiva — v3.5.0-alpha.172.235.

Aggiunge a `delivery_templates` le colonne di stato per l'estrazione item AI
in background: items_extraction_status / items_extraction_msg / items_extraction_at.
Idempotente.

Uso:
    python scripts/migrate_items_extraction_bg.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text
from app.database import engine

_COLS = [
    ("items_extraction_status", "VARCHAR(16) NULL"),
    ("items_extraction_msg", "TEXT NULL"),
    ("items_extraction_at", "DATETIME NULL"),
]


def main():
    insp = inspect(engine)
    if "delivery_templates" not in insp.get_table_names():
        print("Tabella 'delivery_templates' assente — niente da migrare.")
        return
    cols = {c["name"] for c in insp.get_columns("delivery_templates")}
    added = []
    with engine.begin() as conn:
        for col, ddl in _COLS:
            if col not in cols:
                conn.execute(text(f"ALTER TABLE delivery_templates ADD COLUMN {col} {ddl}"))
                added.append(col)
    if added:
        print("ADDED:", ", ".join(added))
    else:
        print("OK: colonne già presenti. Nessuna modifica.")


if __name__ == "__main__":
    main()
