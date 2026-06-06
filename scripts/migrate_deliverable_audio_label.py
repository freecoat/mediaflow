"""v3.5.0-alpha.172.202 — Migrazione: audio override per-deliverable + etichetta
ereditata + link capitolato robusto.

Cosa fa (idempotente):
1. job_deliverables += audio_config_preset_id, audio_config_code, section_label.
2. quote_lines += delivery_template_id.
3. delivery_audio_track_specs += job_deliverable_id E rilassa il NOT NULL su
   delivery_item_id (una traccia ora appartiene a un DeliveryItem *oppure* a un
   JobDeliverable). SQLite non supporta ALTER COLUMN → rebuild tabella
   preservando dati + indici, riusando lo schema reale da sqlite_master.

Lanciabile standalone (`python scripts/migrate_deliverable_audio_label.py`) o
importabile: `from scripts.migrate_deliverable_audio_label import migrate`.
Chiamato anche dal boot (_auto_migrate_columns) per sicurezza zero-step.
"""
from __future__ import annotations
import re
from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine


def _add_columns(engine: Engine) -> list[str]:
    done: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    additive = {
        "job_deliverables": [
            ("audio_config_preset_id", "INTEGER NULL REFERENCES audio_config_presets(id)"),
            ("audio_config_code", "VARCHAR(40) NULL"),
            ("section_label", "VARCHAR(120) NULL"),
        ],
        "quote_lines": [
            ("delivery_template_id", "INTEGER NULL REFERENCES delivery_templates(id)"),
        ],
        "delivery_audio_track_specs": [
            ("job_deliverable_id", "INTEGER NULL REFERENCES job_deliverables(id)"),
        ],
    }
    for table, cols in additive.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in insp.get_columns(table)}
        with engine.begin() as conn:
            for col, ddl in cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    done.append(f"{table}.{col}")
    return done


def _delivery_item_id_is_notnull(engine: Engine) -> bool:
    """True se delivery_audio_track_specs.delivery_item_id ha ancora NOT NULL."""
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(delivery_audio_track_specs)")).fetchall()
    for r in rows:
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        if r[1] == "delivery_item_id":
            return bool(r[3])
    return False


def _relax_item_notnull(engine: Engine) -> bool:
    """Rebuild delivery_audio_track_specs per rendere delivery_item_id nullable.
    Riusa lo schema reale (sqlite_master) togliendo solo il NOT NULL su quella
    colonna. Preserva dati e ricrea gli indici espliciti. Ritorna True se ha
    agito."""
    if not _delivery_item_id_is_notnull(engine):
        return False

    with engine.begin() as conn:
        create_sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='delivery_audio_track_specs'"
        )).scalar()
        if not create_sql:
            return False
        index_sqls = [
            row[0] for row in conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name='delivery_audio_track_specs' AND sql IS NOT NULL"
            )).fetchall()
        ]

        # Togli il NOT NULL SOLO da delivery_item_id. Tollerante a spaziatura.
        # Match: "delivery_item_id" <type> NOT NULL  ->  "delivery_item_id" <type>
        new_create = re.sub(
            r'("?delivery_item_id"?\s+\w+)\s+NOT\s+NULL',
            r'\1',
            create_sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if new_create == create_sql:
            # NOT NULL non trovato nella forma attesa → niente rebuild rischioso.
            raise RuntimeError(
                "migrate_deliverable_audio_label: impossibile localizzare NOT NULL "
                "su delivery_item_id nello schema; rebuild annullato per sicurezza."
            )
        new_create = new_create.replace(
            "delivery_audio_track_specs",
            "delivery_audio_track_specs_new",
            1,
        )

        # Colonne comuni (post ADD COLUMN job_deliverable_id già presente).
        cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(delivery_audio_track_specs)")).fetchall()]
        col_list = ", ".join(f'"{c}"' for c in cols)

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(new_create))
        conn.execute(text(
            f"INSERT INTO delivery_audio_track_specs_new ({col_list}) "
            f"SELECT {col_list} FROM delivery_audio_track_specs"
        ))
        conn.execute(text("DROP TABLE delivery_audio_track_specs"))
        conn.execute(text(
            "ALTER TABLE delivery_audio_track_specs_new "
            "RENAME TO delivery_audio_track_specs"
        ))
        for isql in index_sqls:
            conn.execute(text(isql))
        # Indici per i due FK (idempotente: IF NOT EXISTS).
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_delivery_audio_track_specs_delivery_item_id "
            "ON delivery_audio_track_specs(delivery_item_id)"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_delivery_audio_track_specs_job_deliverable_id "
            "ON delivery_audio_track_specs(job_deliverable_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
    return True


def migrate(engine: Engine) -> dict:
    """Esegue l'intera migrazione. Idempotente. Ritorna un riepilogo."""
    added = _add_columns(engine)
    rebuilt = _relax_item_notnull(engine)
    return {"columns_added": added, "audio_track_table_rebuilt": rebuilt}


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.database import engine  # type: ignore
    result = migrate(engine)
    print("[migrate_deliverable_audio_label]", result)
