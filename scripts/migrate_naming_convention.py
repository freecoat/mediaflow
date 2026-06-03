"""Migrazione v3.5.0-alpha.172.182 — Naming convention strutturata.

Aggiunge:
  - tenants.naming_conventions       TEXT NULL  (JSON {"video":..,"audio":..})
  - delivery_items.naming_convention TEXT NULL  (JSON override per voce)

Idempotente: ALTER solo se la colonna manca. Nessun seed scritto: il default
tenant è costante (DEFAULT_TENANT_NAMING_CONVENTIONS) finché l'utente non salva.

Uso:  python scripts/migrate_naming_convention.py
"""
import sys
from sqlalchemy import inspect, text

sys.path.insert(0, ".")
from app.database import engine  # noqa: E402

TARGETS = [
    ("tenants", "naming_conventions", "TEXT NULL"),
    ("delivery_items", "naming_convention", "TEXT NULL"),
]


def migrate() -> None:
    insp = inspect(engine)
    added = 0
    with engine.begin() as conn:
        for table, col, ddl in TARGETS:
            if table not in insp.get_table_names():
                print(f"[migrate] tabella '{table}' assente — skip")
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            if col not in existing:
                print(f"[migrate] ADD COLUMN {table}.{col}")
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                added += 1
            else:
                print(f"[migrate] {table}.{col} già presente — skip")
    print(f"[migrate] completato ({added} colonne aggiunte).")


if __name__ == "__main__":
    migrate()
