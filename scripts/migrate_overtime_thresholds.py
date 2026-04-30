"""
MediaFlow — migrazione soglie/moltiplicatori straordinari (v3.4.21)

Estende working_hours_policies con i campi necessari al calcolo
automatico degli straordinari sui TimePunch:

  daily_hours_threshold   FLOAT  default 8.0
  weekly_hours_threshold  FLOAT  default 40.0
  overtime_multiplier     FLOAT  default 1.25
  night_multiplier        FLOAT  default 1.50
  sunday_multiplier       FLOAT  default 1.50
  holiday_multiplier      FLOAT  default 2.00
  night_start             TIME   default 22:00
  night_end               TIME   default 06:00

Idempotente: re-eseguibile senza danni.

Esegui:
  python scripts/migrate_overtime_thresholds.py
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
    ("daily_hours_threshold",  "FLOAT NOT NULL DEFAULT 8.0"),
    ("weekly_hours_threshold", "FLOAT NOT NULL DEFAULT 40.0"),
    ("overtime_multiplier",    "FLOAT NOT NULL DEFAULT 1.25"),
    ("night_multiplier",       "FLOAT NOT NULL DEFAULT 1.50"),
    ("sunday_multiplier",      "FLOAT NOT NULL DEFAULT 1.50"),
    ("holiday_multiplier",     "FLOAT NOT NULL DEFAULT 2.00"),
    ("night_start",            "TIME"),
    ("night_end",              "TIME"),
]


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione soglie/moltiplicatori straordinari (v3.4.21)")
    print("─" * 70)

    db = SessionLocal()
    try:
        added = 0
        for col, ddl in COLUMNS:
            if column_exists("working_hours_policies", col):
                print(f"  ✓ working_hours_policies.{col} già presente")
                continue
            print(f"▸ ALTER TABLE working_hours_policies ADD COLUMN {col}")
            db.execute(text(f"ALTER TABLE working_hours_policies ADD COLUMN {col} {ddl}"))
            db.commit()
            added += 1

        # Default night_start / night_end sulle policy esistenti che li hanno NULL
        db.execute(text("""
            UPDATE working_hours_policies
            SET night_start = '22:00'
            WHERE night_start IS NULL
        """))
        db.execute(text("""
            UPDATE working_hours_policies
            SET night_end = '06:00'
            WHERE night_end IS NULL
        """))
        db.commit()

        n_pol = db.execute(text("SELECT COUNT(*) FROM working_hours_policies")).scalar()
        print(f"  · {n_pol} policy totali, {added} colonne aggiunte")

        print("─" * 70)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
