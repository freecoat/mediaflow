"""
MediaFlow — migrazione Booking esecutivo (v3.4.32)

Aggiunge a `bookings` i campi:
  priority               VARCHAR  default 'normal'  (low|normal|high)
  execution_status       VARCHAR  default 'planned' (planned|in_progress|done|not_done)
  not_done_reason        TEXT     null
  count_in_costs         BOOLEAN  default 0
  overtime_status        VARCHAR  default 'none'    (none|pending|approved|rejected)
  original_end_datetime  DATETIME null

Aggiorna anche i preset built-in dei ruoli: aggiunge `approve_overtime`
ai role admin/manager/producer (mappato sui ruoli del sistema permessi).

Idempotente: re-eseguibile senza danni.

Esegui:
  python scripts/migrate_booking_executive.py
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
    ("priority",              "VARCHAR(16) NOT NULL DEFAULT 'normal'"),
    ("execution_status",      "VARCHAR(16) NOT NULL DEFAULT 'planned'"),
    ("not_done_reason",       "TEXT NULL"),
    ("count_in_costs",        "BOOLEAN NOT NULL DEFAULT 0"),
    ("overtime_status",       "VARCHAR(16) NOT NULL DEFAULT 'none'"),
    ("original_end_datetime", "DATETIME NULL"),
]


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione Booking esecutivo (v3.4.32)")
    print("─" * 70)

    db = SessionLocal()
    try:
        # 1. ALTER TABLE bookings
        added = 0
        for col, ddl in COLUMNS:
            if column_exists("bookings", col):
                print(f"  ✓ bookings.{col} già presente")
                continue
            print(f"▸ ALTER TABLE bookings ADD COLUMN {col}")
            db.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {ddl}"))
            db.commit()
            added += 1

        n_book = db.execute(text("SELECT COUNT(*) FROM bookings")).scalar()
        print(f"  · {n_book} booking totali, {added} colonne aggiunte")

        # 2. Mapping permesso approve_overtime → role admin/manager/producer
        print()
        print("▸ Aggiornamento preset permessi (approve_overtime)")
        from app.services.rbac import ensure_built_in_roles, PRESET_PERMISSIONS
        # I preset built-in vengono aggiornati automaticamente al boot
        # (see _ensure_built_in_roles refresh logic). Forziamo qui per chiarezza:
        ensure_built_in_roles(db)
        for code in ("admin", "manager", "producer"):
            row = db.execute(
                text("SELECT permissions FROM roles WHERE code = :c"),
                {"c": code},
            ).first()
            if row:
                import json
                try:
                    perms = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or [])
                except Exception:
                    perms = []
                if "approve_overtime" not in perms:
                    perms.append("approve_overtime")
                    db.execute(
                        text("UPDATE roles SET permissions = :p WHERE code = :c"),
                        {"p": json.dumps(perms), "c": code},
                    )
                    print(f"  · role '{code}': aggiunto approve_overtime")
                else:
                    print(f"  ✓ role '{code}': approve_overtime già presente")
        db.commit()

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
