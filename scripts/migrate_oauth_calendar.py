"""Migrazione non distruttiva — Fase A OAuth calendario.

Aggiunge user_oauth_tokens.auto_sync_calendar + claqo_calendar_id.
Idempotente: ALTER TABLE ADD COLUMN solo se mancanti.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import inspect, text
from app.database import engine


def main():
    insp = inspect(engine)
    if "user_oauth_tokens" not in insp.get_table_names():
        # tabella creata da Base.metadata.create_all() al boot; niente da fare
        print("SKIP: user_oauth_tokens non esiste ancora (verrà creata al boot).")
        return
    cols = {c["name"] for c in insp.get_columns("user_oauth_tokens")}
    alters = [
        ("auto_sync_calendar", "BOOLEAN NOT NULL DEFAULT 0"),
        ("claqo_calendar_id", "VARCHAR(255) NULL"),
    ]
    with engine.begin() as conn:
        for col, ddl in alters:
            if col not in cols:
                print(f"ALTER user_oauth_tokens ADD {col}")
                conn.execute(text(f"ALTER TABLE user_oauth_tokens ADD COLUMN {col} {ddl}"))
    print("OK: migrazione OAuth calendario completata.")


if __name__ == "__main__":
    main()
