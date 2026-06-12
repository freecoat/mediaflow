"""Task 1 — F6 DestructionRequest model + enum destroyed + RBAC.
TDD: questi test devono essere GREEN dopo l'implementazione.
"""
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.models.models import (
    Base,
    AssetMovementType,
    DestructionRequest,
)
from app.services.rbac import ALL_PERMISSION_KEYS, PRESET_PERMISSIONS


# ── Fixture engine in-memory ──────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session
        session.rollback()


# ── Test 1: AssetMovementType.destroyed esiste ───────────────────

def test_asset_movement_type_destroyed_exists():
    """AssetMovementType deve avere il membro 'destroyed' per F6."""
    assert hasattr(AssetMovementType, "destroyed"), (
        "AssetMovementType deve avere il membro 'destroyed'"
    )
    assert AssetMovementType.destroyed.value == "destroyed"


# ── Test 2: DestructionRequest default status + created_at ───────

def test_destruction_request_defaults(db):
    """DestructionRequest: status default = 'requested', created_at valorizzato.
    asset_id è richiesto (NOT NULL) — usiamo un id fittizio; in SQLite senza
    PRAGMA foreign_keys=ON la FK non viene verificata nel test in-memory.
    """
    req = DestructionRequest(
        tenant_id=1,
        asset_id=999,   # id fittizio — FK non enforced in SQLite in-memory di default
        reason="Test reason",
        requested_by_user_id=None,
    )
    db.add(req)
    db.flush()
    assert req.status == "requested"
    assert req.created_at is not None


# ── Test 3: asset_movements NON ha CHECK constraint su enum ───────

def test_asset_movements_no_check_constraint_on_type(engine):
    """La colonna movement_type di asset_movements è VARCHAR puro.
    SQLite non deve avere CHECK constraint che limiti i valori dell'enum:
    verifichiamo via sqlite_master che il DDL non contenga CHECK sul campo.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='asset_movements'"
            )
        ).fetchone()

    assert row is not None, "Tabella asset_movements non trovata"
    ddl = row[0].upper()
    # Il DDL non deve contenere CHECK (...) sul campo movement_type
    # Un VARCHAR generico non lo ha; lo avrebbe solo se usassimo
    # Column(Enum(...)) con SQLAlchemy che emette CHECK su SQLite.
    assert "CHECK" not in ddl, (
        "asset_movements non deve avere CHECK constraint sull'enum "
        f"(DDL: {row[0][:200]})"
    )


# ── Test 4: permesso approve_destruction in RBAC ─────────────────

def test_approve_destruction_in_all_permission_keys():
    """approve_destruction deve essere registrato in PERMISSIONS/ALL_PERMISSION_KEYS."""
    assert "approve_destruction" in ALL_PERMISSION_KEYS, (
        "'approve_destruction' non trovato in ALL_PERMISSION_KEYS"
    )


def test_approve_destruction_in_admin_preset():
    """Il preset admin deve includere approve_destruction."""
    assert "approve_destruction" in PRESET_PERMISSIONS["admin"], (
        "'approve_destruction' non trovato nel preset admin"
    )
