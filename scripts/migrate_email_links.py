"""Migrazione Client email F2 — tabella email_links (idempotente).
Creata anche da Base.metadata.create_all() al boot; questo script per DB esistenti.
Uso: .venv/Scripts/python.exe scripts/migrate_email_links.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect
from app.database import engine
from app.models.models import EmailLink  # noqa: F401


def main():
    insp = inspect(engine)
    if "email_links" in insp.get_table_names():
        print("[migrate_email_links] tabella email_links gia presente - nessuna azione.")
        return
    EmailLink.__table__.create(bind=engine)
    print("[migrate_email_links] tabella email_links creata.")


if __name__ == "__main__":
    main()
