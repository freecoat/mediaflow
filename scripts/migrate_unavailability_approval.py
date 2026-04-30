"""
MediaFlow — workflow approvazione ferie/malattia/permessi (v3.4.22)

Estende `resource_unavailabilities` con i campi per il flusso pending → approved/rejected:

  status               TEXT NOT NULL DEFAULT 'approved'   (back-compat: tutto pre-esistente è già 'approved')
  requested_by_user_id INTEGER NULL                        FK users.id
  approved_by_user_id  INTEGER NULL                        FK users.id
  approved_at          DATETIME NULL
  rejection_reason     TEXT NULL
  created_at           DATETIME NULL                        (default valutato a runtime)

Logica di compatibilità: i record esistenti vengono marcati `approved` per non
introdurre regressioni sul blocco pianificazione esistente.

Esegui:
  python scripts/migrate_unavailability_approval.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine


COLUMNS = [
    ("status",                "TEXT NOT NULL DEFAULT 'approved'"),
    ("requested_by_user_id",  "INTEGER"),
    ("approved_by_user_id",   "INTEGER"),
    ("approved_at",           "DATETIME"),
    ("rejection_reason",      "TEXT"),
    ("created_at",            "DATETIME"),
]


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · workflow approvazione ferie/malattia (v3.4.22)")
    print("─" * 70)

    db = SessionLocal()
    try:
        added = 0
        for col, ddl in COLUMNS:
            if column_exists("resource_unavailabilities", col):
                print(f"  ✓ resource_unavailabilities.{col} già presente")
                continue
            print(f"▸ ALTER TABLE resource_unavailabilities ADD COLUMN {col}")
            db.execute(text(f"ALTER TABLE resource_unavailabilities ADD COLUMN {col} {ddl}"))
            db.commit()
            added += 1

        # Backfill status a 'approved' per record che lo hanno NULL
        db.execute(text("""
            UPDATE resource_unavailabilities
            SET status = 'approved'
            WHERE status IS NULL OR status = ''
        """))
        # Backfill created_at con valore corrente per record vecchi
        db.execute(text("""
            UPDATE resource_unavailabilities
            SET created_at = CURRENT_TIMESTAMP
            WHERE created_at IS NULL
        """))
        db.commit()

        n_total = db.execute(text("SELECT COUNT(*) FROM resource_unavailabilities")).scalar()
        n_pending = db.execute(text("SELECT COUNT(*) FROM resource_unavailabilities WHERE status='pending'")).scalar()
        print(f"  · {n_total} unavailability totali, {n_pending} pending, {added} colonne aggiunte")

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
