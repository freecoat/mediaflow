"""F1 — processo risultato job agent: done probe → proposta asset."""
import pytest

from app.models.models import (
    Tenant, User, UserRole, StorageVolume, AgentNode,
    AgentJobType, AgentJobStatus, AssetProposedState,
)
from app.services.agent_queue import enqueue_job, claim_next_job
from app.routers.agent_api import process_job_result


def _setup(db):
    db.add(Tenant(id=1, name="T", slug="t1"))
    db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff)
    db.add(u)
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    db.add(v)
    agent = AgentNode(tenant_id=1, name="ag", auth_token_hash="d" * 64)
    db.add(agent)
    db.flush()
    return u, v, agent


def test_probe_done_creates_proposal(db):
    u, v, agent = _setup(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                      payload={"volume_id": v.id, "rel_path": "OUT/x.mov"},
                      requested_by_user_id=u.id)
    claim_next_job(db, agent)
    asset = process_job_result(db, job, status="done", result={
        "rel_path": "OUT/x.mov", "file_size": 10, "mime_type": "video/quicktime",
        "checksum_xxhash": "ee11ee11ee11ee11",
        "tech_specs": {"tool": "ffprobe"},
    })
    assert job.status == AgentJobStatus.done
    assert asset is not None
    assert asset.proposed_state == AssetProposedState.pending_review
    assert job.asset_id == asset.id


def test_failed_job_no_proposal(db):
    u, v, agent = _setup(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                      payload={"volume_id": v.id, "rel_path": "OUT/x.mov"})
    claim_next_job(db, agent)
    asset = process_job_result(db, job, status="failed", result=None,
                               error="path not found")
    assert job.status == AgentJobStatus.failed
    assert asset is None
