from datetime import UTC, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import (
    Base, Tenant, Client, Project, Job, Asset, AssetType, AssetProposedState,
    JobDeliverable, DeliverableAsset, DeliverableStatus, DeliverableNature,
    NotificationKind, User, UserRole,
)
from app.services.deliverable_assets import _resync_primary


def _session():
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, expire_on_commit=False)()


def test_notificationkind_has_supersede():
    assert NotificationKind.deliverable_reopened_supersede.value == "deliverable_reopened_supersede"


def test_deliverableasset_supersede_columns_exist():
    cols = {c.name for c in DeliverableAsset.__table__.columns}
    assert {"superseded_at", "superseded_by_id", "supersede_reason"} <= cols


def test_resync_primary_ignores_superseded():
    db = _session()
    db.add(Tenant(id=1, name="T", slug="t")); db.flush()
    cl = Client(tenant_id=1, name="C"); db.add(cl); db.flush()
    pr = Project(tenant_id=1, code="P", title="P", client_id=cl.id); db.add(pr); db.flush()
    u = User(id=1, tenant_id=1, email="a@t.l", full_name="A", hashed_password="x",
             role=UserRole.admin, is_active=True); db.add(u); db.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    a_old = Asset(tenant_id=1, filename="old.mov", original_name="old.mov", file_path="/o",
                  file_size=1, mime_type="video/quicktime", asset_type=AssetType.video,
                  uploaded_by=1, project_id=pr.id, proposed_state=AssetProposedState.confirmed,
                  created_at=now); db.add(a_old)
    a_new = Asset(tenant_id=1, filename="new.mov", original_name="new.mov", file_path="/n",
                  file_size=1, mime_type="video/quicktime", asset_type=AssetType.video,
                  uploaded_by=1, project_id=pr.id, proposed_state=AssetProposedState.confirmed,
                  created_at=now); db.add(a_new); db.flush()
    jd = JobDeliverable(tenant_id=1, job_id=1, name="DCP", nature=DeliverableNature.digital,
                        status=DeliverableStatus.delivered); db.add(jd); db.flush()
    link_old = DeliverableAsset(tenant_id=1, job_deliverable_id=jd.id, asset_id=a_old.id)
    db.add(link_old); db.flush()
    link_new = DeliverableAsset(tenant_id=1, job_deliverable_id=jd.id, asset_id=a_new.id)
    db.add(link_new); db.flush()
    # marca old come superseded
    link_old.superseded_at = now
    link_old.superseded_by_id = link_new.id
    db.flush()
    _resync_primary(db, jd)
    assert jd.digital_asset_id == a_new.id   # il primario NON è il superseded
