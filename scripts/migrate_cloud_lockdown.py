"""Migrazione Content Lockdown (TPN) — v3.5.0-alpha.172.195.

Aggiunge a `tenants` le colonne del megaswitch egress cloud:
  lockdown_master, cloud_ai_enabled, web_search_enabled, enrichment_enabled,
  lockdown_at, lockdown_by, lockdown_reason.

Idempotente. Default OPEN + sub True = retrocompat totale (i tenant esistenti
restano pienamente aperti finché un admin non attiva il lockdown da UI).

Nota: il boot (_auto_migrate_columns in app/main.py) applica già le stesse
ALTER. Questo script è per chi preferisce migrare esplicitamente prima del boot.
"""
from sqlalchemy import inspect, text
from app.database import engine


ALTERS = [
    ("lockdown_master", "VARCHAR(10) NOT NULL DEFAULT 'OPEN'"),
    ("cloud_ai_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("web_search_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("enrichment_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("lockdown_at", "DATETIME NULL"),
    ("lockdown_by", "INTEGER NULL"),
    ("lockdown_reason", "VARCHAR(255) NULL"),
]


def migrate() -> None:
    print("-- Migrazione Content Lockdown (TPN) ----------------")
    insp = inspect(engine)
    if "tenants" not in insp.get_table_names():
        print("[SKIP] tabella tenants assente (DB non inizializzato).")
        return
    cols = {c["name"] for c in insp.get_columns("tenants")}
    with engine.begin() as conn:
        for col, ddl in ALTERS:
            if col in cols:
                print(f"[OK] tenants.{col} già presente")
                continue
            conn.execute(text(f"ALTER TABLE tenants ADD COLUMN {col} {ddl}"))
            print(f"[ADD] tenants.{col}")
    print("-- Fatto. Default: OPEN + sub attivi (retrocompat). --")


if __name__ == "__main__":
    migrate()
