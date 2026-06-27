"""Migrazione non distruttiva — Acquisizioni Fase 1.

Crea le tabelle acquisitions/contacts/activities/acquisition_departments.
Idempotente (create_all salta le tabelle esistenti).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import engine
from app.models.models import (
    Acquisition, Contact, Activity, acquisition_departments,  # noqa: F401
)
from app.models.models import Base


def main():
    """Crea le tabelle acquisizioni idempotentemente."""
    Base.metadata.create_all(engine, tables=[
        Acquisition.__table__, Contact.__table__,
        Activity.__table__, acquisition_departments,
    ])
    print("OK: tabelle acquisizioni create/verificate.")


if __name__ == "__main__":
    main()
