"""F5 Task 1 — Test modello TransferOrder + adapter registry.

4 casi:
  (a) modello: ordine manual con asset_ids JSON [1,2], default status requested, created_at
  (b) registry: ADAPTERS contiene "manual" (mode manual) e "aspera" (mode agent)
  (c) ADAPTERS["aspera"].build_job_payload(order, files) → dict corretto
  (d) manual.build_job_payload → NotImplementedError
"""
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Importa dopo che il modello è definito
from app.models.models import Base, TransferOrder
from app.services.transfer_adapters import ADAPTERS, ManualAdapter, AsperaAdapter


# ── fixture DB in-memory ───────────────────────────────────────────────────────

@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ── (a) modello ────────────────────────────────────────────────────────────────

def test_transfer_order_model_defaults(db: Session):
    """Crea un ordine manual con asset_ids JSON, verifica default status e created_at."""
    order = TransferOrder(
        tenant_id=1,
        tool="manual",
        destination="FTP server interno",
        asset_ids=[1, 2],
    )
    db.add(order)
    db.flush()

    assert order.id is not None
    assert order.status == "requested"
    assert order.asset_ids == [1, 2]
    assert order.created_at is not None
    assert order.link_url is None
    assert order.link_expires_at is None
    assert order.agent_job_id is None
    assert order.closed_at is None


# ── (b) registry ───────────────────────────────────────────────────────────────

def test_adapters_registry_keys():
    """ADAPTERS ha esattamente manual e aspera."""
    assert "manual" in ADAPTERS
    assert "aspera" in ADAPTERS
    assert ADAPTERS["manual"].mode == "manual"
    assert ADAPTERS["aspera"].mode == "agent"


# ── (c) aspera payload ─────────────────────────────────────────────────────────

def test_aspera_build_job_payload():
    """AsperaAdapter.build_job_payload ritorna dict con tool, files, destination, extra_args."""
    # Crea un ordine finto (non persistito, bastano gli attributi)
    order = TransferOrder(
        tenant_id=1,
        tool="aspera",
        destination="user@host:/incoming",
        asset_ids=[3, 4],
    )
    files = [
        {"volume_id": 1, "rel_path": "shots/A001.mxf"},
        {"volume_id": 1, "rel_path": "audio/mix.wav"},
    ]
    adapter = ADAPTERS["aspera"]
    payload = adapter.build_job_payload(order, files)

    assert payload["tool"] == "aspera"
    assert payload["files"] == files
    assert payload["destination"] == "user@host:/incoming"
    assert payload["extra_args"] == []


# ── (d) manual → NotImplementedError ──────────────────────────────────────────

def test_manual_build_job_payload_raises():
    """ManualAdapter.build_job_payload solleva NotImplementedError (mode manual non lo usa)."""
    order = TransferOrder(
        tenant_id=1,
        tool="manual",
        destination="share interno",
        asset_ids=[1],
    )
    adapter = ADAPTERS["manual"]
    with pytest.raises(NotImplementedError):
        adapter.build_job_payload(order, [])
