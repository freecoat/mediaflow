"""F3 — enqueue_preview idempotente + apply_preview_result."""
import os
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (Base, Asset, AssetType, StorageVolume, Tenant,
                               AgentJob, AgentJobType, AgentJobStatus)
from app.services.asset_preview import (enqueue_preview, apply_preview_result,
                                        apply_preview_failure, s3_preview_config)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.flush()
    yield s
    s.close()


def _asset(db, **kw):
    """Costruttore Asset con campi obbligatori minimi."""
    defaults = dict(
        tenant_id=1,
        filename="test.mxf",
        original_name="test.mxf",
        file_path="",
        file_size=1,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
    )
    defaults.update(kw)
    a = Asset(**defaults)
    db.add(a)
    db.flush()
    return a


def _volume(db, **kw):
    """StorageVolume minimo."""
    defaults = dict(tenant_id=1, name="SAN", mount_path="/mnt/san")
    defaults.update(kw)
    v = StorageVolume(**defaults)
    db.add(v)
    db.flush()
    return v


# ── Test 1: enqueue crea job ─────────────────────────────────────────────────

def test_enqueue_crea_job(db, monkeypatch):
    """enqueue_preview crea AgentJob preview con payload corretto e setta asset.preview_status=queued."""
    # Rimuoviamo PREVIEW_S3_BUCKET per forzare mode=server
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)

    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path="OUT/test.mxf")

    job = enqueue_preview(db, a, requested_by_user_id=None)

    assert job is not None
    assert job.type == AgentJobType.preview
    assert job.status == AgentJobStatus.queued
    assert job.tenant_id == 1

    payload = job.payload
    assert payload["asset_id"] == a.id
    assert payload["rel_path"] == "OUT/test.mxf"
    assert payload["volume_id"] == v.id
    assert payload["upload"]["mode"] == "server"

    # Asset aggiornato
    db.refresh(a)
    assert a.preview_status == "queued"
    assert a.preview_error is None


# ── Test 2: enqueue idempotente ──────────────────────────────────────────────

@pytest.mark.parametrize("initial_status", [
    AgentJobStatus.queued,
    AgentJobStatus.claimed,
    AgentJobStatus.running,
])
def test_enqueue_idempotente(db, monkeypatch, initial_status):
    """Secondo enqueue ritorna lo stesso job id se pending."""
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)

    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path="OUT/a.mxf")

    job1 = enqueue_preview(db, a)
    # Simula stato avanzato manualmente
    job1.status = initial_status
    db.flush()

    job2 = enqueue_preview(db, a)

    assert job2.id == job1.id


# ── Test 3: enqueue dopo failed = nuovo job ──────────────────────────────────

def test_enqueue_dopo_failed_nuovo_job(db, monkeypatch):
    """Dopo un job failed è possibile ri-accodare e si ottiene un nuovo job id."""
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)

    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path="OUT/b.mxf")

    job1 = enqueue_preview(db, a)
    job1.status = AgentJobStatus.failed
    db.flush()

    job2 = enqueue_preview(db, a)

    assert job2.id != job1.id
    assert job2.status == AgentJobStatus.queued


# ── Test 4: enqueue valida asset ─────────────────────────────────────────────

def test_enqueue_valida_asset_senza_rel_path(db):
    """ValueError se asset senza rel_path."""
    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path=None)

    with pytest.raises(ValueError, match="rel_path"):
        enqueue_preview(db, a)


def test_enqueue_valida_asset_senza_volume(db):
    """ValueError se asset senza storage_volume_id."""
    a = _asset(db, storage_volume_id=None, rel_path="OUT/c.mxf")

    with pytest.raises(ValueError, match="storage_volume_id"):
        enqueue_preview(db, a)


# ── Test 5: s3_preview_config None senza bucket ──────────────────────────────

def test_s3_preview_config_none(monkeypatch):
    """s3_preview_config() ritorna None se manca PREVIEW_S3_BUCKET."""
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    assert s3_preview_config() is None


def test_s3_preview_config_presente(monkeypatch):
    """s3_preview_config() ritorna dict con bucket se PREVIEW_S3_BUCKET è impostato."""
    monkeypatch.setenv("PREVIEW_S3_BUCKET", "my-bucket")
    monkeypatch.setenv("PREVIEW_S3_REGION", "eu-west-1")
    monkeypatch.setenv("PREVIEW_S3_ACCESS_KEY", "AK")
    monkeypatch.setenv("PREVIEW_S3_SECRET_KEY", "SK")

    cfg = s3_preview_config()
    assert cfg is not None
    assert cfg["bucket"] == "my-bucket"
    assert cfg["region"] == "eu-west-1"


# ── Test 6: apply_result server file esistente ───────────────────────────────

def test_apply_result_server_ok(db, tmp_path, monkeypatch):
    """apply_preview_result con file locale esistente → status ready, meta popolata."""
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    # Monkeypatcha PREVIEW_DIR nel modulo
    import app.services.asset_preview as svc
    monkeypatch.setattr(svc, "PREVIEW_DIR", tmp_path)

    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path="OUT/d.mxf")
    job = enqueue_preview(db, a)

    # Crea il file preview dove il service si aspetta di trovarlo
    preview_file = tmp_path / str(a.tenant_id) / f"{a.id}.mp4"
    preview_file.parent.mkdir(parents=True, exist_ok=True)
    preview_file.write_bytes(b"fake_proxy_content")

    result = {
        "uploaded": "server",
        "preview_path": str(preview_file),
        "start_tc": "01:00:00:00",
        "fps": 25.0,
        "duration_sec": 5400.0,
        "burned_tc": True,
    }

    asset_out = apply_preview_result(db, job, result)

    assert asset_out is not None
    db.refresh(asset_out)
    assert asset_out.preview_status == "ready"
    assert asset_out.preview_storage == "local"
    assert asset_out.preview_meta is not None
    assert asset_out.preview_meta["fps"] == 25.0
    assert asset_out.preview_generated_at is not None


# ── Test 7: apply_result server file mancante ────────────────────────────────

def test_apply_result_server_file_mancante(db, tmp_path, monkeypatch):
    """apply_preview_result con file mancante → status failed con errore."""
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    import app.services.asset_preview as svc
    monkeypatch.setattr(svc, "PREVIEW_DIR", tmp_path)

    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path="OUT/e.mxf")
    job = enqueue_preview(db, a)

    result = {
        "uploaded": "server",
        "preview_path": str(tmp_path / "nonexistent" / "file.mp4"),
        "start_tc": "00:00:00:00",
        "fps": 25.0,
        "duration_sec": 100.0,
        "burned_tc": False,
    }

    asset_out = apply_preview_result(db, job, result)

    assert asset_out is not None
    db.refresh(asset_out)
    assert asset_out.preview_status == "failed"
    assert asset_out.preview_error is not None
    assert len(asset_out.preview_error) > 0


# ── Test 8: apply_failure ────────────────────────────────────────────────────

def test_apply_failure(db, monkeypatch):
    """apply_preview_failure → status failed + preview_error impostato."""
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)

    v = _volume(db)
    a = _asset(db, storage_volume_id=v.id, rel_path="OUT/f.mxf")
    job = enqueue_preview(db, a)

    asset_out = apply_preview_failure(db, job, "ffmpeg crash SIGSEGV")

    assert asset_out is not None
    db.refresh(asset_out)
    assert asset_out.preview_status == "failed"
    assert "ffmpeg" in asset_out.preview_error
