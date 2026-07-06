"""Migrazione non distruttiva — Fase B calendario.

Crea la tabella calendar_events. Idempotente (create_all salta l'esistente).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine
from app.models.models import Base, CalendarEvent  # noqa: F401


def main():
    Base.metadata.create_all(engine, tables=[CalendarEvent.__table__])
    print("OK: tabella calendar_events creata/verificata.")


if __name__ == "__main__":
    main()
