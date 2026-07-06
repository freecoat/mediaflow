"""Migrazione Fase D — tabella document_links (idempotente).

La tabella è creata anche da Base.metadata.create_all() al boot; questo script
serve per DB esistenti dove si preferisce una migrazione esplicita + verifica.
Uso: .venv/Scripts/python.exe scripts/migrate_documents.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect
from app.database import engine
from app.models.models import Base, DocumentLink  # noqa: F401


def main():
    insp = inspect(engine)
    if "document_links" in insp.get_table_names():
        print("[migrate_documents] tabella document_links già presente — nessuna azione.")
        return
    DocumentLink.__table__.create(bind=engine)
    print("[migrate_documents] tabella document_links creata.")


if __name__ == "__main__":
    main()
