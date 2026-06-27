"""Migrazione non distruttiva — v3.5.0-alpha.172.237.
Aggiunge tenants.web_sources (JSON lista domini per incrocio web AI).
Idempotente. Seed default sui tenant con valore NULL."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sqlalchemy import inspect, text
from app.database import engine

DEFAULT_WEB_SOURCES = ["filmitalia.org", "cinema.cultura.gov.it", "imdb.com", "mymovies.it"]


def main():
    insp = inspect(engine)
    if "tenants" not in insp.get_table_names():
        print("Tabella 'tenants' assente."); return
    cols = {c["name"] for c in insp.get_columns("tenants")}
    if "web_sources" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tenants ADD COLUMN web_sources JSON NULL"))
        print("ADDED tenants.web_sources")
    # seed default dove NULL
    with engine.begin() as conn:
        conn.execute(text("UPDATE tenants SET web_sources = :v WHERE web_sources IS NULL"),
                     {"v": json.dumps(DEFAULT_WEB_SOURCES)})
    print("OK: seed default applicato dove mancante.")


if __name__ == "__main__":
    main()
