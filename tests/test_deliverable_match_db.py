"""F2 — candidate set + match_proposal contro DB in-memory."""
from app.models.models import (
    Tenant, User, UserRole, Project, Client, Job, JobDeliverable,
    DeliverableStatus, DeliveryItem, DeliveryTemplate, Container, VideoCodec,
    Resolution, FrameRate, StorageVolume, Asset, AssetType, AssetStatus,
    AssetContentState, AssetProposedState,
)
from app.services.deliverable_match import match_proposal, rank_candidates


def _seed(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff); db.add(u)
    cli = Client(tenant_id=1, name="Sky"); db.add(cli); db.flush()
    proj = Project(tenant_id=1, code="GOMORRA", title="Gomorra S3",
                   client_id=cli.id); db.add(proj); db.flush()
    # Job requires client_id (NOT NULL FK)
    job = Job(tenant_id=1, project_id=proj.id, client_id=cli.id,
              code="GOMORRA-J01", title="J01"); db.add(job); db.flush()
    cont = Container(tenant_id=1, name="QuickTime", extension="mov")
    cod = VideoCodec(tenant_id=1, name="ProRes 422 HQ", family="prores")
    res = Resolution(tenant_id=1, name="HD 1080", width=1920, height=1080)
    fr = FrameRate(tenant_id=1, name="25", fps=25.0)
    db.add_all([cont, cod, res, fr]); db.flush()
    # DeliveryItem requires delivery_template_id (NOT NULL FK)
    tmpl = DeliveryTemplate(tenant_id=1, code="TEST-TMPL", name="Test Template")
    db.add(tmpl); db.flush()
    item = DeliveryItem(tenant_id=1, name="Master ProRes",
                        delivery_template_id=tmpl.id,
                        container_id=cont.id, video_codec_id=cod.id,
                        resolution_id=res.id, frame_rate_id=fr.id)
    db.add(item); db.flush()
    deliv = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01 master",
                           file_naming="GOMORRA_S03_EP01",
                           delivery_item_id=item.id,
                           status=DeliverableStatus.planned)
    db.add(deliv); db.flush()
    return u, proj, job, deliv


def _proposal(db, u, vol_id=1, rel="OUT/GOMORRA/GOMORRA_S03_EP01_PRORES.mov"):
    a = Asset(tenant_id=1, filename=rel.split("/")[-1], original_name=rel.split("/")[-1],
              file_path=f"agent://{vol_id}/{rel}", storage_volume_id=vol_id,
              rel_path=rel, asset_type=AssetType.video, mime_type="video/quicktime",
              file_size=10, uploaded_by=u.id, status=AssetStatus.uploaded,
              content_state=AssetContentState.online,
              proposed_state=AssetProposedState.pending_review,
              tech_specs_json={"container": "mov,mp4", "video": {
                  "codec": "prores", "width": 1920, "height": 1080,
                  "frame_rate": "25/1"}})
    db.add(a); db.flush()
    return a


def test_match_proposal_strong_sets_matched_id(db):
    u, proj, job, deliv = _seed(db)
    db.add(StorageVolume(tenant_id=1, name="SAN", mount_path="/m",
                         watch_dirs=["/OUT"])); db.flush()
    a = _proposal(db, u)
    match_proposal(db, a)
    assert a.matched_deliverable_id == deliv.id


def test_match_proposal_excludes_already_linked(db):
    u, proj, job, deliv = _seed(db)
    deliv.digital_asset_id = 999
    db.add(StorageVolume(tenant_id=1, name="SAN", mount_path="/m",
                         watch_dirs=["/OUT"])); db.flush()
    a = _proposal(db, u)
    match_proposal(db, a)
    assert a.matched_deliverable_id is None


def test_rank_candidates_orders_by_score(db):
    u, proj, job, deliv = _seed(db)
    a = _proposal(db, u)
    ranked = rank_candidates(db, a)
    assert ranked and ranked[0]["deliverable_id"] == deliv.id
    assert ranked[0]["strength"] in ("strong", "weak")
