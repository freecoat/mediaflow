# tests/test_f3_preview_model.py
"""F3 (spec 2026-06-11) — campi preview su Asset + auto_preview su StorageVolume."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, Asset, AssetType, StorageVolume


def _session():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_asset_preview_fields_default():
    db = _session()
    a = Asset(
        tenant_id=1,
        filename="x.mxf",
        original_name="x.mxf",
        file_path="",
        file_size=1,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
    )
    db.add(a)
    db.commit()
    db.expire(a)
    a = db.get(Asset, a.id)
    assert a.preview_status == "none"
    assert a.preview_path is None
    assert a.preview_storage is None
    assert a.preview_error is None
    assert a.preview_meta is None
    assert a.preview_generated_at is None
    # Verifica che il server_default "none" sia presente nella colonna reale del DB
    raw = db.execute(
        text("SELECT preview_status FROM assets WHERE id=:i"), {"i": a.id}
    ).scalar()
    assert raw == "none"


def test_volume_auto_preview_default_false():
    db = _session()
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    db.add(v)
    db.commit()
    db.expire(v)
    v = db.get(StorageVolume, v.id)
    assert v.auto_preview is False
