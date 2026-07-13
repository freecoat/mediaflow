"""Task 2 — media_actions.associate: link + supersede + auto-reset stato (Fase B)."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base, Tenant, Client, Project, Asset, AssetType, AssetProposedState, User, UserRole,
    PhysicalAsset, PhysicalAssetKind,
    JobDeliverable, DeliverableAsset, DeliverableStatus, DeliverableNature,
)
from app.services import media_actions

PRJ_CODE = "PRJ001"


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture
def ctx():
    """Fixture analoga a tests/test_media_library.py: Tenant(1), Client, Project
    (code=PRJ001), utente admin, 2 Asset video confirmed (a_old/a_new), 1
    PhysicalAsset, 1 JobDeliverable delivered (a_old già linkato) e 1
    JobDeliverable in_progress."""
    db = _session()

    db.add(Tenant(id=1, name="Tenant 1", slug="t1"))
    db.add(Tenant(id=2, name="Tenant 2", slug="t2"))
    db.flush()

    client = Client(tenant_id=1, name="Cliente Uno")
    db.add(client)
    db.flush()

    project = Project(tenant_id=1, code=PRJ_CODE, title="Progetto Uno", client_id=client.id)
    db.add(project)
    db.flush()

    admin = User(
        id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
        hashed_password="x", role=UserRole.admin, is_active=True,
    )
    db.add(admin)
    db.flush()

    now = datetime.now(UTC).replace(tzinfo=None)

    a_old = Asset(
        tenant_id=1, filename="old.mov", original_name="old.mov", file_path="/vol/old.mov",
        file_size=100, mime_type="video/quicktime", asset_type=AssetType.video,
        uploaded_by=admin.id, project_id=project.id,
        proposed_state=AssetProposedState.confirmed, created_at=now,
    )
    a_new = Asset(
        tenant_id=1, filename="new.mov", original_name="new.mov", file_path="/vol/new.mov",
        file_size=100, mime_type="video/quicktime", asset_type=AssetType.video,
        uploaded_by=admin.id, project_id=project.id,
        proposed_state=AssetProposedState.confirmed, created_at=now,
    )
    other_tenant_asset = Asset(
        tenant_id=2, filename="other.mov", original_name="other.mov", file_path="/vol/other.mov",
        file_size=10, mime_type="video/quicktime", asset_type=AssetType.video,
        uploaded_by=admin.id, project_id=None,
        proposed_state=AssetProposedState.confirmed, created_at=now,
    )
    db.add_all([a_old, a_new, other_tenant_asset])
    db.flush()

    lto = PhysicalAsset(
        tenant_id=1, kind=PhysicalAssetKind.lto, label="LTO-SMK-001",
        project_id=project.id, created_at=now,
    )
    db.add(lto)
    db.flush()

    jd_delivered = JobDeliverable(
        tenant_id=1, job_id=1, name="DCP INTEROP",
        nature=DeliverableNature.digital, status=DeliverableStatus.delivered,
    )
    db.add(jd_delivered)
    db.flush()

    jd_progress = JobDeliverable(
        tenant_id=1, job_id=1, name="ProRes Master",
        nature=DeliverableNature.digital, status=DeliverableStatus.in_progress,
    )
    db.add(jd_progress)
    db.flush()

    da_old = DeliverableAsset(
        tenant_id=1, job_deliverable_id=jd_delivered.id, asset_id=a_old.id,
    )
    db.add(da_old)
    jd_delivered.digital_asset_id = a_old.id
    db.commit()

    return {
        "db": db, "admin": admin, "project": project, "client": client,
        "a_old": a_old, "a_new": a_new, "other_tenant_asset": other_tenant_asset,
        "lto": lto, "jd_delivered": jd_delivered, "jd_progress": jd_progress,
    }


def test_associate_creates_link(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_progress"]
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}])
    db.commit()
    assert out["linked"] == 1
    assert jd.digital_asset_id == ctx["a_new"].id


def test_associate_supersedes_active_same_nature(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_delivered"]
    # a_old già linkato attivo (nel fixture)
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}],
                                  reason="QC negativo")
    db.commit()
    assert out["superseded"] == 1
    from app.models.models import DeliverableAsset
    old = db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == jd.id,
        DeliverableAsset.asset_id == ctx["a_old"].id).first()
    assert old.superseded_at is not None
    assert old.supersede_reason == "QC negativo"
    assert jd.digital_asset_id == ctx["a_new"].id


def test_associate_auto_reset_status_from_delivered(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_delivered"]
    from app.models.models import DeliverableStatus
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}])
    db.commit()
    assert out["status_reset"] is True
    assert jd.status == DeliverableStatus.in_progress
    assert jd.qc_substatus is None


def test_associate_no_reset_when_in_progress(ctx):
    db, admin, jd = ctx["db"], ctx["admin"], ctx["jd_progress"]
    from app.models.models import DeliverableStatus
    out = media_actions.associate(db, admin, deliverable_id=jd.id,
                                  items=[{"nature": "digital", "id": ctx["a_new"].id}])
    db.commit()
    assert out["status_reset"] is False
    assert jd.status == DeliverableStatus.in_progress


def test_associate_deliverable_other_tenant_raises(ctx):
    db, admin = ctx["db"], ctx["admin"]
    import pytest
    with pytest.raises(media_actions.MediaActionError):
        media_actions.associate(db, admin, deliverable_id=999999,
                                items=[{"nature": "digital", "id": ctx["a_new"].id}])
