"""F1 asset registry — modelli StorageVolume/AgentNode/AgentJob + estensioni Asset."""
import pytest
from datetime import datetime

from app.models.models import (
    Tenant, User, UserRole,
    StorageVolume, AgentNode, AgentJob,
    AgentJobType, AgentJobStatus,
    Asset, AssetType, AssetStatus,
    AssetContentState, AssetProposedState,
)


def _tenant(db, tid=1):
    t = Tenant(id=tid, name="T", slug=f"t{tid}", tech_specs_refresh_days=30)
    db.add(t)
    db.flush()
    return t


def test_storage_volume_create(db):
    _tenant(db)
    v = StorageVolume(tenant_id=1, name="SAN-01", mount_path="/Volumes/SAN01",
                      watch_dirs=["/OUT"], read_only=True)
    db.add(v)
    db.flush()
    assert v.id is not None
    assert v.is_active is True
    assert v.watch_dirs == ["/OUT"]


def test_agent_node_create(db):
    _tenant(db)
    a = AgentNode(tenant_id=1, name="agent-mac-01",
                  auth_token_hash="a" * 64, capabilities=["probe", "checksum"])
    db.add(a)
    db.flush()
    assert a.id is not None
    assert a.last_heartbeat_at is None
    assert a.is_active is True


def test_agent_job_lifecycle_fields(db):
    _tenant(db)
    a = AgentNode(tenant_id=1, name="ag", auth_token_hash="b" * 64)
    db.add(a)
    db.flush()
    j = AgentJob(tenant_id=1, agent_id=a.id, type=AgentJobType.probe,
                 payload={"volume_id": 1, "rel_path": "OUT/P001/file.mov"})
    db.add(j)
    db.flush()
    assert j.status == AgentJobStatus.queued
    assert j.progress == 0
    assert j.result is None


def test_asset_new_columns_defaults(db):
    _tenant(db)
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u)
    db.flush()
    asset = Asset(tenant_id=1, filename="f.mov", original_name="f.mov",
                  file_path="agent://1/OUT/f.mov", asset_type=AssetType.video,
                  mime_type="video/quicktime", file_size=100, uploaded_by=u.id)
    db.add(asset)
    db.flush()
    assert asset.content_state == AssetContentState.online
    assert asset.proposed_state == AssetProposedState.confirmed
    assert asset.storage_volume_id is None
    assert asset.checksum_xxhash is None
