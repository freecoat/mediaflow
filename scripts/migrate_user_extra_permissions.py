"""
MediaFlow — permessi extra per-utente (v3.4.25)

Aggiunge `users.extra_permissions JSON NULL` per supportare permessi additivi
sul singolo utente sopra il ruolo. Idempotente.

Esegui:
  python scripts/migrate_user_extra_permissions.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect, text
from app.database import engine


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · permessi extra per-utente (v3.4.25)")
    print("─" * 70)

    if not column_exists("users", "extra_permissions"):
        print("  → ALTER TABLE users ADD COLUMN extra_permissions JSON NULL")
        with engine.begin() as conn:
            # SQLite: TEXT con default NULL (SQLAlchemy serializza JSON come TEXT)
            conn.execute(text("ALTER TABLE users ADD COLUMN extra_permissions TEXT NULL"))
        print("  ✓ Colonna creata")
    else:
        print("  ✓ Colonna users.extra_permissions già presente")

    print("─" * 70)
    print("✅ Migrazione completata.")


if __name__ == "__main__":
    migrate()
