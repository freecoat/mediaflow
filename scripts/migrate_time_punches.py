"""
MediaFlow — migrazione: TimePunch (timbrature/presenze, sezione HR)

Crea la tabella `time_punches` se non esiste. Modello separato dal Booking:
il booking esprime intenzione di pianificazione (chi sarà su quale job e quando),
il TimePunch registra una presenza effettiva (chi è stato a lavoro e per quanto).

Tutte le risorse umane (interne + freelance) rendicontano qui le ore lavorate.

Idempotente: se la tabella esiste già non fa nulla. Viene creata in toto via
`create_tables()` (SQLAlchemy `Base.metadata.create_all`).

Esegui:
  python scripts/migrate_time_punches.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect
from app.database import SessionLocal, engine, create_tables
# Import necessario per registrare TimePunch su Base.metadata
from app.models import TimePunch  # noqa: F401


def table_exists(table: str) -> bool:
    return table in inspect(engine).get_table_names()


def migrate():
    print("▸ MediaFlow · migrazione time_punches (HR)")
    print("─" * 60)

    existed = table_exists("time_punches")
    create_tables()

    db = SessionLocal()
    try:
        if existed:
            print("  ✓ time_punches già presente")
        else:
            print("  ✓ time_punches creata")

        print("─" * 60)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
