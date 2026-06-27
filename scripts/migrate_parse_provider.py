"""Migrazione non distruttiva — v3.5.0-alpha.172.234.

Aggiunge `users.parse_ai_provider` (motore di parsing capitolati esplicito).
None = automatico (modello più forte configurato). Idempotente.

Uso:
    python scripts/migrate_parse_provider.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text
from app.database import engine


def main():
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        print("Tabella 'users' assente — niente da migrare.")
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "parse_ai_provider" in cols:
        print("OK: users.parse_ai_provider già presente. Nessuna modifica.")
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN parse_ai_provider VARCHAR(32) NULL"))
    print("ADDED: users.parse_ai_provider (NULL = automatico).")


if __name__ == "__main__":
    main()
