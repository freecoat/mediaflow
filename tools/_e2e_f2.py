"""E2E F2 — watch → proposta agent_watch → auto-match → conferma → qc.

Guida il pacchetto agent (scan_volume, 2 cicli per stabilità) e posta il
risultato scan via gli endpoint HTTP reali /agent-api contro il server live.
Verifica: proposta creata (registered_via=agent_watch), match forte sul
JobDeliverable atteso, conferma → digital_asset_id + status=qc.
"""
import sys
import requests

from app.database import SessionLocal
from app.models.models import (
    Tenant, User, Client, Project, Job, JobDeliverable, DeliverableStatus,
    DeliveryTemplate, DeliveryItem, Container, VideoCodec, Resolution, FrameRate,
    StorageVolume, AgentNode, AgentJobType, Asset, AssetProposedState,
)
from app.services.agent_queue import generate_agent_token, enqueue_scan_if_absent
from app.services.asset_registry import confirm_proposal
from app.services.deliverable_match import link_deliverable_on_confirm
from agent.watch import WatchState, scan_volume

BASE = "http://127.0.0.1:8000"
MOUNT = r"C:\temp\san01"
REL = "OUT/GOMORRA/GOMORRA_S03_EP01_PRORES.mov"

db = SessionLocal()
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}")


# ── pre-clean idempotente: rimuovi artefatti di run precedenti ──
for _a in db.query(Asset).filter(Asset.registered_via == "agent_watch").all():
    db.delete(_a)
for _p in db.query(Project).filter(Project.code == "GOMORRA").all():
    for _j in db.query(Job).filter(Job.project_id == _p.id).all():
        for _d in db.query(JobDeliverable).filter(JobDeliverable.job_id == _j.id).all():
            db.delete(_d)
        db.delete(_j)
    db.delete(_p)
for _v in db.query(StorageVolume).filter(StorageVolume.name.like("SAN-F2%")).all():
    db.delete(_v)
for _ag in db.query(AgentNode).filter(AgentNode.name.like("agent-f2%")).all():
    db.delete(_ag)
for _t in db.query(DeliveryTemplate).filter(DeliveryTemplate.code == "E2E-TMPL").all():
    for _di in db.query(DeliveryItem).filter(DeliveryItem.delivery_template_id == _t.id).all():
        db.delete(_di)
    db.delete(_t)
for _M, _nm in [(Container, "QuickTime-E2E"), (VideoCodec, "ProRes-E2E"),
                (Resolution, "HD1080-E2E"), (FrameRate, "25-E2E")]:
    for _o in db.query(_M).filter(_M.name == _nm).all():
        db.delete(_o)
db.commit()

# ── seed dominio (project GOMORRA + deliverable atteso ProRes/HD/25) ──
tenant = db.get(Tenant, 1)
check("tenant 1", tenant is not None)
admin = db.query(User).filter(User.tenant_id == 1).first()
cli = db.query(Client).filter(Client.tenant_id == 1).first()
if cli is None:
    cli = Client(tenant_id=1, name="E2E Client"); db.add(cli); db.flush()
proj = Project(tenant_id=1, code="GOMORRA", title="Gomorra E2E", client_id=cli.id)
db.add(proj); db.flush()
job = Job(tenant_id=1, project_id=proj.id, client_id=cli.id,
          code="GOMORRA-E2E", title="J"); db.add(job); db.flush()
cont = Container(tenant_id=1, name="QuickTime-E2E", extension="mov")
cod = VideoCodec(tenant_id=1, name="ProRes-E2E", family="prores")
res = Resolution(tenant_id=1, name="HD1080-E2E", width=1920, height=1080)
fr = FrameRate(tenant_id=1, name="25-E2E", fps=25.0)
db.add_all([cont, cod, res, fr]); db.flush()
tmpl = DeliveryTemplate(tenant_id=1, code="E2E-TMPL", name="E2E"); db.add(tmpl); db.flush()
item = DeliveryItem(tenant_id=1, delivery_template_id=tmpl.id, name="Master",
                    container_id=cont.id, video_codec_id=cod.id,
                    resolution_id=res.id, frame_rate_id=fr.id); db.add(item); db.flush()
deliv = JobDeliverable(tenant_id=1, job_id=job.id, name="EP01 master",
                       file_naming="GOMORRA_S03_EP01", delivery_item_id=item.id,
                       status=DeliverableStatus.planned); db.add(deliv); db.flush()
deliv_id = deliv.id

vol = StorageVolume(tenant_id=1, name="SAN-F2-e2e", mount_path=MOUNT,
                    watch_dirs=["OUT"], read_only=True); db.add(vol); db.flush()
vol_id = vol.id
plain, h = generate_agent_token()
agent = AgentNode(tenant_id=1, name="agent-f2-e2e", auth_token_hash=h); db.add(agent)
db.flush()
agent_id = agent.id
db.commit()
print(f"seed: project={proj.id} deliv={deliv_id} vol={vol_id} agent={agent_id}")

# ── agent-side watch: 2 cicli per stabilità ──
st = WatchState()
c1 = scan_volume(MOUNT, ["OUT"], st)
check("watch ciclo 1 = nessun file stabile", c1 == [])
c2 = scan_volume(MOUNT, ["OUT"], st)
rels = [x["rel_path"] for x in c2]
check("watch ciclo 2 = file stabile rilevato", REL in rels)
probe_items = c2
# La macchina di test non ha ffprobe → tech_specs.tool='none'. Inietto le specs
# realistiche (come le produrrebbe ffprobe in facility) per esercitare il match.
for it in probe_items:
    if it.get("rel_path") == REL:
        it["tech_specs"] = {"tool": "ffprobe", "container": "mov,mp4",
                            "video": {"codec": "prores", "width": 1920,
                                      "height": 1080, "frame_rate": "25/1"}}

# ── accoda scan + claim via /agent-api + post result ──
enqueue_scan_if_absent(db, tenant_id=1, volume_id=vol_id)
db.commit()
S = requests.Session(); S.headers["X-Agent-Token"] = plain
hb = S.post(f"{BASE}/agent-api/heartbeat",
            json={"version": "0.1.0", "capabilities": ["probe", "checksum", "scan"],
                  "volumes": [{"volume_id": vol_id}]}, timeout=30)
check("heartbeat 200", hb.status_code == 200)
cl = S.post(f"{BASE}/agent-api/jobs/claim", timeout=30)
claimed = cl.json().get("job")
check("claim job scan", claimed and claimed["type"] == "scan")
rr = S.post(f"{BASE}/agent-api/jobs/{claimed['id']}/result",
            json={"status": "done",
                  "result": {"volume_id": vol_id, "items": probe_items}}, timeout=60)
check("post scan result 200", rr.status_code == 200)

# ── verifica proposta + match ──
db.expire_all()
prop = db.query(Asset).filter(Asset.tenant_id == 1,
                              Asset.storage_volume_id == vol_id,
                              Asset.rel_path == REL,
                              Asset.proposed_state == AssetProposedState.pending_review
                              ).order_by(Asset.id.desc()).first()
check("proposta creata", prop is not None)
if prop:
    check("registered_via = agent_watch", prop.registered_via == "agent_watch")
    check("rel_path corretto", prop.rel_path == REL)
    check("match forte -> matched_deliverable_id", prop.matched_deliverable_id == deliv_id)

# ── conferma → link deliverable → qc ──
if prop:
    confirm_proposal(db, prop, user_id=admin.id if admin else None)
    link_deliverable_on_confirm(db, prop, deliverable_id=deliv_id,
                                user_id=admin.id if admin else None)
    db.flush()
    d2 = db.get(JobDeliverable, deliv_id)
    check("digital_asset_id = asset", d2.digital_asset_id == prop.id)
    check("deliverable status = qc", d2.status == DeliverableStatus.qc)

# ── cleanup E2E ──
db.expire_all()
from app.models.models import AgentJob
for j in db.query(AgentJob).filter(AgentJob.tenant_id == 1,
                                   AgentJob.type == AgentJobType.scan).all():
    if (j.payload or {}).get("volume_id") == vol_id:
        db.delete(j)
if prop:
    db.delete(prop)
db.delete(db.get(JobDeliverable, deliv_id))
db.delete(db.get(DeliveryItem, item.id))
db.delete(db.get(DeliveryTemplate, tmpl.id))
for o in (cont, cod, res, fr):
    db.delete(db.get(type(o), o.id))
db.delete(db.get(Job, job.id))
db.delete(db.get(Project, proj.id))
db.delete(db.get(AgentNode, agent_id))
db.delete(db.get(StorageVolume, vol_id))
db.commit()
print("cleanup E2E fatto")

passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"\n=== E2E F2: {passed}/{total} ===")
sys.exit(0 if passed == total else 1)
