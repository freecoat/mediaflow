"""F2 — conferma proposta con deliverable → digital_asset_id + status=qc."""
import pytest
from app.models.models import (
    Tenant, User, UserRole, Client, Project, Job, JobDeliverable,
    DeliverableStatus, StorageVolume, Asset, AssetType, AssetStatus,
    AssetContentState, AssetProposedState,
)
from app.services.asset_registry import confirm_proposal
from app.services.deliverable_match import link_deliverable_on_confirm


def _seed(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff); db.add(u)
    cli = Client(tenant_id=1, name="Sky"); db.add(cli); db.flush()
    proj = Project(tenant_id=1, code="G", title="G", client_id=cli.id)
    db.add(proj); db.flush()
    job = Job(tenant_id=1, project_id=proj.id, client_id=cli.id, code="J", title="J")
    db.add(job); db.flush()
    d = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01",
                       status=DeliverableStatus.planned); db.add(d); db.flush()
    a = Asset(tenant_id=1, filename="f.mov", original_name="f.mov",
              file_path="agent://1/OUT/G/f.mov", storage_volume_id=None,
              rel_path="OUT/G/f.mov", asset_type=AssetType.video,
              mime_type="video/quicktime", file_size=1, uploaded_by=u.id,
              status=AssetStatus.uploaded, content_state=AssetContentState.online,
              proposed_state=AssetProposedState.pending_review); db.add(a); db.flush()
    return u, d, a


def test_link_on_confirm_sets_digital_asset_and_qc(db):
    u, d, a = _seed(db)
    confirm_proposal(db, a, user_id=u.id)
    link_deliverable_on_confirm(db, a, deliverable_id=d.id, user_id=u.id)
    assert d.digital_asset_id == a.id
    assert d.status == DeliverableStatus.qc


def test_link_rejects_cross_tenant(db):
    u, d, a = _seed(db)
    with pytest.raises(Exception):
        link_deliverable_on_confirm(db, a, deliverable_id=99999, user_id=u.id)
