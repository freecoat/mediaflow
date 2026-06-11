"""test_f4_membership_nullable.py — RED/GREEN per F4: AssetMembership.asset_id nullable.

Test A: modello accetta asset_id=None (in-memory SQLite).
Test B: migrazione idempotente su DB con tabella legacy NOT NULL.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine, text, inspect as sa_inspect
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Test A — modello accetta asset_id=None
# ---------------------------------------------------------------------------

def test_membership_asset_id_nullable_model():
    """AssetMembership con asset_id=None deve essere accettata senza IntegrityError."""
    from app.models.models import Base, AssetMembership

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        m = AssetMembership(
            tenant_id=1,
            physical_asset_id=1,
            asset_id=None,
            path_on_media="/X/",
        )
        session.add(m)
        session.flush()
        session.commit()

    # Verifica via raw SQL
    with engine.connect() as conn:
        row = conn.execute(text("SELECT asset_id FROM asset_memberships WHERE id=1")).fetchone()
    assert row is not None
    assert row[0] is None, f"Atteso NULL, trovato {row[0]}"


# ---------------------------------------------------------------------------
# Test B — migrazione legacy (table rebuild idempotente)
# ---------------------------------------------------------------------------

def _create_legacy_table(conn):
    """Crea asset_memberships con asset_id INTEGER NOT NULL (vecchio schema)."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS asset_memberships (
            id INTEGER PRIMARY KEY,
            tenant_id INTEGER NOT NULL DEFAULT 1 REFERENCES tenants(id),
            physical_asset_id INTEGER NOT NULL REFERENCES physical_assets(id),
            asset_id INTEGER NOT NULL REFERENCES assets(id),
            path_on_media VARCHAR(512),
            checksum VARCHAR(128),
            file_size INTEGER,
            notes TEXT,
            added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            added_by_user_id INTEGER REFERENCES users(id),
            removed_at DATETIME,
            removed_by_user_id INTEGER REFERENCES users(id)
        )
    """))
    # Inserisci una riga con asset_id valorizzato
    conn.execute(text("""
        INSERT INTO asset_memberships
            (id, tenant_id, physical_asset_id, asset_id, path_on_media, checksum, file_size, notes)
        VALUES (1, 1, 2, 3, '/TEST/', 'abc123', 4096, 'nota test')
    """))


def test_membership_nullable_rebuild(tmp_path):
    """Migrazione legacy: rebuild rende asset_id nullable, preserva dati, è idempotente."""
    from app.main import _rebuild_asset_memberships_nullable

    db_path = str(tmp_path / "test_legacy.db")
    engine = create_engine(f"sqlite:///{db_path}", echo=False)

    # Crea schema legacy (NOT NULL su asset_id)
    with engine.begin() as conn:
        _create_legacy_table(conn)

    # Verifica precondizione: asset_id NOT NULL
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(asset_memberships)")).fetchall()
    col_map = {r[1]: r for r in rows}  # name -> (cid, name, type, notnull, dflt, pk)
    assert col_map["asset_id"][3] == 1, "Precondizione: asset_id deve essere NOT NULL"

    # --- Prima chiamata: rebuild ---
    _rebuild_asset_memberships_nullable(engine)

    # Verifica 1: asset_id ora nullable
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(asset_memberships)")).fetchall()
    col_map2 = {r[1]: r for r in rows}
    assert col_map2["asset_id"][3] == 0, "Dopo rebuild: asset_id deve essere nullable (notnull=0)"

    # Verifica 2: riga dati preservata
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM asset_memberships WHERE id=1")).fetchone()
    assert row is not None, "Riga id=1 deve essere preservata dopo rebuild"
    row_dict = dict(zip(col_map2.keys(), row))
    assert row_dict["tenant_id"] == 1
    assert row_dict["physical_asset_id"] == 2
    assert row_dict["asset_id"] == 3
    assert row_dict["path_on_media"] == "/TEST/"
    assert row_dict["checksum"] == "abc123"
    assert row_dict["file_size"] == 4096
    assert row_dict["notes"] == "nota test"

    # Verifica 3: INSERT con asset_id NULL ora funziona
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO asset_memberships
                (tenant_id, physical_asset_id, asset_id, path_on_media)
            VALUES (1, 5, NULL, '/ORPHAN/')
        """))
    with engine.connect() as conn:
        null_row = conn.execute(text(
            "SELECT asset_id FROM asset_memberships WHERE path_on_media='/ORPHAN/'"
        )).fetchone()
    assert null_row is not None
    assert null_row[0] is None, "INSERT con asset_id=NULL deve funzionare dopo rebuild"

    # --- Seconda chiamata: no-op idempotente ---
    _rebuild_asset_memberships_nullable(engine)  # non deve sollevare eccezioni

    # Verifica che i dati siano ancora intatti
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM asset_memberships")).scalar()
    assert count == 2, f"Attese 2 righe dopo seconda chiamata, trovate {count}"
