# tests/test_f4_ticket_model.py
"""F4 (spec 2026-06-11) — Modello ArchiveTicket: default, kind archive con asset,
restore con deliverable."""
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base,
    ArchiveTicket,
    Asset, AssetType,
    JobDeliverable, DeliverableNature,
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_default_status_and_created_at():
    """status default = 'requested', created_at valorizzato automaticamente."""
    db = _session()
    t = ArchiveTicket(kind="archive", asset_id=None)
    db.add(t)
    db.commit()
    db.expire(t)
    t = db.get(ArchiveTicket, t.id)

    assert t.status == "requested"
    assert isinstance(t.created_at, datetime)
    assert t.closed_at is None
    assert t.tenant_id == 1


def test_kind_archive_with_asset():
    """Ticket archive legato a un asset digitale."""
    db = _session()
    asset = Asset(
        tenant_id=1,
        filename="master.mxf",
        original_name="master.mxf",
        file_path="/san/master.mxf",
        file_size=1_000_000,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
    )
    db.add(asset)
    db.flush()

    t = ArchiveTicket(kind="archive", asset_id=asset.id)
    db.add(t)
    db.commit()
    db.expire(t)
    t = db.get(ArchiveTicket, t.id)

    assert t.kind == "archive"
    assert t.asset_id == asset.id
    assert t.job_deliverable_id is None
    assert t.physical_asset_id is None
    assert t.status == "requested"


def test_kind_restore_with_deliverable():
    """Ticket restore legato a un job_deliverable."""
    db = _session()
    d = JobDeliverable(
        tenant_id=1,
        job_id=1,
        name="Mix 5.1",
        nature=DeliverableNature.digital,
    )
    db.add(d)
    db.flush()

    t = ArchiveTicket(kind="restore", job_deliverable_id=d.id, note="Urgente")
    db.add(t)
    db.commit()
    db.expire(t)
    t = db.get(ArchiveTicket, t.id)

    assert t.kind == "restore"
    assert t.job_deliverable_id == d.id
    assert t.asset_id is None
    assert t.note == "Urgente"
    assert t.status == "requested"
