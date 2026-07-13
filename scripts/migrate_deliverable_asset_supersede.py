"""Aggiunge le colonne supersede a deliverable_assets (Fase B Media Library).
Idempotente: rilanciabile senza effetti doppi."""
from sqlalchemy import inspect, text
from app.database import engine


def run():
    insp = inspect(engine)
    if "deliverable_assets" not in insp.get_table_names():
        print("[migrate_supersede] tabella deliverable_assets assente, skip")
        return
    cols = {c["name"] for c in insp.get_columns("deliverable_assets")}
    alters = [
        ("superseded_at", "DATETIME NULL"),
        ("superseded_by_id", "INTEGER NULL REFERENCES deliverable_assets(id)"),
        ("supersede_reason", "VARCHAR(255) NULL"),
    ]
    added = 0
    with engine.begin() as conn:
        for col, ddl in alters:
            if col not in cols:
                conn.execute(text(f"ALTER TABLE deliverable_assets ADD COLUMN {col} {ddl}"))
                added += 1
    print(f"[migrate_supersede] colonne aggiunte: {added}")


if __name__ == "__main__":
    run()
