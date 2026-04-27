"""
MediaFlow — migrazione schema sconti multilivello su quotazioni

Aggiunge:
  - QuoteLine.line_discount_pct (sconto sulla singola voce, positivo = riduzione)
  - Quote.subtotal_gross (subtotale prima di qualsiasi sconto, mostrato in PDF)
  - Quote.category_discounts (JSON {nome_categoria: pct} per sconti su raggruppamento dinamico)

Per ogni quotazione esistente popola subtotal_gross con il valore corrente di subtotal
(prima della migrazione subtotal era già post-allowance ma pre-sconti, quindi coincide
con il nuovo subtotal_gross).

Esegui una sola volta dopo l'aggiornamento del modello:
  python scripts/migrate_quote_discounts.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Console Windows usa cp1252 di default e rompe i caratteri unicode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine, create_tables
from app.models import Quote


def column_exists(table: str, column: str) -> bool:
    return column in [c["name"] for c in inspect(engine).get_columns(table)]


def migrate():
    print("▸ MediaFlow · migrazione sconti multilivello quotazioni")
    print("─" * 60)

    create_tables()

    db = SessionLocal()
    try:
        alter_statements = [
            ("quote_lines", "line_discount_pct", "REAL DEFAULT 0.0"),
            ("quotes", "subtotal_gross", "REAL DEFAULT 0.0"),
            ("quotes", "category_discounts", "JSON"),
        ]
        for table, col, ddl in alter_statements:
            if not column_exists(table, col):
                print(f"▸ ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                db.commit()
            else:
                print(f"  (skip) {table}.{col} già esiste")

        backfilled = 0
        for q in db.query(Quote).all():
            if (q.subtotal_gross or 0.0) == 0.0 and (q.subtotal or 0.0) > 0.0:
                q.subtotal_gross = q.subtotal
                backfilled += 1
        if backfilled:
            db.commit()
            print(f"✓ Popolato subtotal_gross su {backfilled} quotazioni esistenti")
        else:
            print("  (nessuna quotazione da backfill)")

        print("─" * 60)
        print("✓ Migrazione completata")
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
