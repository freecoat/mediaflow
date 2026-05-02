"""
MediaFlow — migrazione versioning quote (v3.4.39).

Aggiunge le colonne necessarie per la duplicazione semplice e il versioning
delle quotazioni con migrazione del Job:

- quotes.parent_quote_id           — FK quotes.id NULL (catena versioni)
- quotes.superseded_by_id          — FK quotes.id NULL (puntatore al successore approvato)
- quote_lines.parent_line_id       — FK quote_lines.id NULL (eredità riga in V_n+1)

Idempotente: ALTER TABLE solo se la colonna manca.
Lo stesso check è eseguito al boot da `_auto_migrate_columns()` in main.py;
questo script serve come fallback esplicito (strumenti.bat/sh opzione [N]).

Esegui:
  python scripts/migrate_quote_versioning.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text, inspect
from app.database import engine


def migrate():
    print("▸ MediaFlow · versioning quote (v3.4.39)")
    print("─" * 70)

    insp = inspect(engine)

    if "quotes" not in insp.get_table_names():
        print("✗ Tabella `quotes` mancante. Esegui prima il setup base.")
        return 1

    qcols = {c["name"] for c in insp.get_columns("quotes")}
    qlcols = {c["name"] for c in insp.get_columns("quote_lines")}

    quote_alter = [
        ("parent_quote_id", "INTEGER NULL REFERENCES quotes(id)"),
        ("superseded_by_id", "INTEGER NULL REFERENCES quotes(id)"),
    ]
    qline_alter = [
        ("parent_line_id", "INTEGER NULL REFERENCES quote_lines(id)"),
    ]

    added = 0
    with engine.begin() as conn:
        for col, ddl in quote_alter:
            if col in qcols:
                print(f"  ✓ quotes.{col} già presente")
            else:
                print(f"  + quotes.{col} → ALTER TABLE")
                conn.execute(text(f"ALTER TABLE quotes ADD COLUMN {col} {ddl}"))
                added += 1
        for col, ddl in qline_alter:
            if col in qlcols:
                print(f"  ✓ quote_lines.{col} già presente")
            else:
                print(f"  + quote_lines.{col} → ALTER TABLE")
                conn.execute(text(f"ALTER TABLE quote_lines ADD COLUMN {col} {ddl}"))
                added += 1

    print("─" * 70)
    print(f"✔ Migrazione [N] completata. {added} colonna/e aggiunta/e.")
    print("  Lo status enum `superseded` non richiede ALTER (SQLite memorizza")
    print("  enum come VARCHAR, validazione lato Python).")
    return 0


if __name__ == "__main__":
    sys.exit(migrate())
