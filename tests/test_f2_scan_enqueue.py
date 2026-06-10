"""F2 — enqueue_scan_if_absent: un solo scan queued per volume."""
from app.models.models import Tenant, StorageVolume, AgentJob, AgentJobStatus, AgentJobType
from app.services.agent_queue import enqueue_scan_if_absent


def test_enqueue_scan_dedup(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/m", watch_dirs=["/OUT"])
    db.add(v); db.flush()
    j1 = enqueue_scan_if_absent(db, tenant_id=1, volume_id=v.id)
    j2 = enqueue_scan_if_absent(db, tenant_id=1, volume_id=v.id)
    assert j1.id == j2.id
    n = db.query(AgentJob).filter(AgentJob.type == AgentJobType.scan,
                                  AgentJob.status == AgentJobStatus.queued).count()
    assert n == 1
