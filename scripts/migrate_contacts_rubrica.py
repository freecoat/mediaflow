"""v3.5.0-alpha.172.246 — Migrazione Client email F3: Rubrica Contatti.

Cosa fa (idempotente):
1. contacts += company_text (VARCHAR(255) NULL), source (VARCHAR(20) NOT NULL
   DEFAULT 'manual').
2. contacts.client_id: da NOT NULL a nullable. SQLite non supporta
   ALTER COLUMN -> rebuild tabella riusando lo schema reale da sqlite_master
   (stesso pattern di migrate_deliverable_audio_label.py: _relax_item_notnull),
   preservando dati + indici.
3. CREATE TABLE se mancanti: contact_acquisitions, contact_projects
   (create_all le crea gia' per DB nuovi; qui esplicito per DB esistenti,
   pattern migrate_documents.py).

Lanciabile standalone (`python scripts/migrate_contacts_rubrica.py`) o
importabile: `from scripts.migrate_contacts_rubrica import migrate`.
Chiamato anche dal boot (_auto_migrate_columns) per sicurezza zero-step.
"""
from __future__ import annotations
import re
from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine


def _add_columns(engine: Engine) -> list[str]:
    done: list[str] = []
    insp = inspect(engine)
    if "contacts" not in insp.get_table_names():
        return done
    existing = {c["name"] for c in insp.get_columns("contacts")}
    additive = [
        ("company_text", "VARCHAR(255) NULL"),
        ("source", "VARCHAR(20) NOT NULL DEFAULT 'manual'"),
    ]
    with engine.begin() as conn:
        for col, ddl in additive:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE contacts ADD COLUMN {col} {ddl}"))
                done.append(f"contacts.{col}")
    return done


def _client_id_is_notnull(engine: Engine) -> bool:
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(contacts)")).fetchall()
    for r in rows:
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        if r[1] == "client_id":
            return bool(r[3])
    return False


def _relax_client_id_notnull(engine: Engine) -> bool:
    """Rebuild contacts per rendere client_id nullable. Riusa lo schema reale
    (sqlite_master) togliendo solo il NOT NULL su quella colonna. Preserva
    dati e ricrea gli indici espliciti. Ritorna True se ha agito."""
    if not _client_id_is_notnull(engine):
        return False

    with engine.begin() as conn:
        create_sql = conn.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='contacts'"
        )).scalar()
        if not create_sql:
            return False
        index_sqls = [
            row[0] for row in conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND tbl_name='contacts' AND sql IS NOT NULL"
            )).fetchall()
        ]

        # Togli il NOT NULL SOLO da client_id. Tollerante a spaziatura.
        new_create = re.sub(
            r'("?client_id"?\s+\w+)\s+NOT\s+NULL',
            r'\1',
            create_sql,
            count=1,
            flags=re.IGNORECASE,
        )
        if new_create == create_sql:
            raise RuntimeError(
                "migrate_contacts_rubrica: impossibile localizzare NOT NULL "
                "su client_id nello schema; rebuild annullato per sicurezza."
            )
        new_create = new_create.replace("contacts", "contacts_new", 1)

        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(contacts)")).fetchall()]
        col_list = ", ".join(f'"{c}"' for c in cols)

        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text(new_create))
        conn.execute(text(
            f"INSERT INTO contacts_new ({col_list}) SELECT {col_list} FROM contacts"
        ))
        conn.execute(text("DROP TABLE contacts"))
        conn.execute(text("ALTER TABLE contacts_new RENAME TO contacts"))
        for isql in index_sqls:
            conn.execute(text(isql))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_contacts_client_id ON contacts(client_id)"))
        conn.execute(text("PRAGMA foreign_keys=ON"))
    return True


def _create_join_tables(engine: Engine) -> list[str]:
    from app.models.models import ContactAcquisition, ContactProject
    done: list[str] = []
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    if "contact_acquisitions" not in tables:
        ContactAcquisition.__table__.create(bind=engine)
        done.append("contact_acquisitions")
    if "contact_projects" not in tables:
        ContactProject.__table__.create(bind=engine)
        done.append("contact_projects")
    return done


def migrate(engine: Engine) -> dict:
    """Esegue l'intera migrazione. Idempotente. Ritorna un riepilogo."""
    added = _add_columns(engine)
    rebuilt = _relax_client_id_notnull(engine)
    tables = _create_join_tables(engine)
    return {"columns_added": added, "contacts_rebuilt": rebuilt, "tables_created": tables}


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from app.database import engine  # type: ignore
    result = migrate(engine)
    print("[migrate_contacts_rubrica]", result)
