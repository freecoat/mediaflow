"""
MediaFlow — migrazione: QuoteLine.category_override

Aggiunge una colonna `category_override` (TEXT NULL) sulla tabella `quote_lines`.
Se presente, sostituisce `price_item.category` nel raggruppamento dell'editor,
PDF, CSV/Excel export. Permette di:
  - spostare voci tra categorie senza cambiare la voce di listino
  - dare una categoria a voci libere (senza price_item_id)

Idempotente: se la colonna esiste già, non fa nulla.

Esegui:
  python scripts/migrate_quote_category_override.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine, create_tables


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione category_override su quote_lines")
    print("─" * 60)

    create_tables()
    db = SessionLocal()
    try:
        if not column_exists("quote_lines", "category_override"):
            print("▸ ALTER TABLE quote_lines ADD COLUMN category_override TEXT")
            db.execute(text("ALTER TABLE quote_lines ADD COLUMN category_override TEXT"))
            db.commit()
            print("  ✓ aggiunta")
        else:
            print("  ✓ category_override già presente")

        print("─" * 60)
        print("Migrazione completata.")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
