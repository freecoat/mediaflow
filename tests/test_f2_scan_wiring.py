"""F2 — process_job_result: probe→match; scan→N proposte+match."""
from app.models.models import (
    Tenant, User, UserRole, Client, Project, Job, JobDeliverable,
    DeliverableStatus, DeliveryItem, Container, VideoCodec, Resolution, FrameRate,
    StorageVolume, AgentNode, AgentJobType, AssetProposedState,
)
from app.services.agent_queue import enqueue_job, claim_next_job
from app.routers.agent_api import process_job_result


def _seed(db):
    db.add(Tenant(id=1, name="T", slug="t1")); db.flush()
    u = User(tenant_id=1, email="op@mediaflow.it", hashed_password="x",
             full_name="Op", role=UserRole.staff); db.add(u)
    cli = Client(tenant_id=1, name="Sky"); db.add(cli); db.flush()
    proj = Project(tenant_id=1, code="GOMORRA", title="G", client_id=cli.id)
    db.add(proj); db.flush()
    job = Job(tenant_id=1, project_id=proj.id, client_id=cli.id, code="J01", title="J01")
    db.add(job); db.flush()
    cont = Container(tenant_id=1, name="QuickTime", extension="mov")
    cod = VideoCodec(tenant_id=1, name="ProRes 422 HQ", family="prores")
    res = Resolution(tenant_id=1, name="HD", width=1920, height=1080)
    fr = FrameRate(tenant_id=1, name="25", fps=25.0)
    db.add_all([cont, cod, res, fr]); db.flush()
    # DeliveryItem needs a delivery_template_id (NOT NULL) — create a throwaway template
    from app.models.models import DeliveryTemplate
    tmpl = DeliveryTemplate(tenant_id=1, code="TMPL", name="T"); db.add(tmpl); db.flush()
    item = DeliveryItem(tenant_id=1, delivery_template_id=tmpl.id, name="m",
                        container_id=cont.id, video_codec_id=cod.id,
                        resolution_id=res.id, frame_rate_id=fr.id); db.add(item); db.flush()
    d = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01",
                       file_naming="GOMORRA_S03_EP01", delivery_item_id=item.id,
                       status=DeliverableStatus.planned); db.add(d); db.flush()
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/m", watch_dirs=["/OUT"])
    db.add(v)
    ag = AgentNode(tenant_id=1, name="ag", auth_token_hash="d"*64); db.add(ag)
    db.flush()
    return u, v, ag, d


PROBE = {"rel_path": "OUT/GOMORRA/GOMORRA_S03_EP01_PRORES.mov", "file_size": 10,
         "mime_type": "video/quicktime", "checksum_xxhash": "aa11aa11aa11aa11",
         "tech_specs": {"container": "mov,mp4", "video": {
             "codec": "prores", "width": 1920, "height": 1080,
             "frame_rate": "25/1"}}}


def test_probe_done_runs_match(db):
    u, v, ag, d = _seed(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                      payload={"volume_id": v.id, "rel_path": PROBE["rel_path"]},
                      requested_by_user_id=u.id)
    claim_next_job(db, ag)
    asset = process_job_result(db, job, status="done", result=PROBE)
    assert asset is not None
    assert asset.matched_deliverable_id == d.id


def test_scan_creates_multiple_proposals(db):
    u, v, ag, d = _seed(db)
    job = enqueue_job(db, tenant_id=1, type=AgentJobType.scan,
                      payload={"volume_id": v.id}, requested_by_user_id=u.id)
    claim_next_job(db, ag)
    p2 = dict(PROBE, rel_path="OUT/GOMORRA/altro.wav",
              checksum_xxhash="bb22bb22bb22bb22", mime_type="audio/wav",
              tech_specs={"container": "wav"})
    res = process_job_result(db, job, status="done",
                             result={"volume_id": v.id, "items": [PROBE, p2]})
    from app.models.models import Asset
    assets = db.query(Asset).filter(Asset.proposed_state ==
                                    AssetProposedState.pending_review).all()
    assert len(assets) == 2
