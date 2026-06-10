"""E2E F1 — prova il loop completo server <-> agent contro il server LIVE su :8000.

Crea volume+agent+job nel DB, poi guida il pacchetto agent attraverso gli endpoint
HTTP reali /agent-api (auth X-Agent-Token), verifica che nasca la proposta Asset.
Non tocca l'autenticazione utente: usa solo l'auth agent.
"""
import sys
import requests

from app.database import SessionLocal
from app.models.models import (
    Tenant, User, StorageVolume, AgentNode, AgentJob, AgentJobType,
    Asset, AssetProposedState,
)
from app.services.agent_queue import generate_agent_token, enqueue_job
from agent.probe import build_probe_result

BASE = "http://127.0.0.1:8000"
MOUNT = r"C:\temp\san01"
REL = "OUT/P001/test.mov"

db = SessionLocal()
results = []


def check(name, cond):
    results.append((name, bool(cond)))
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}")


# --- setup: tenant garantito, user admin esistente, volume, agent, job ---
tenant = db.get(Tenant, 1)
check("tenant 1 esiste", tenant is not None)
admin = db.query(User).filter(User.tenant_id == 1).first()
check("almeno un user", admin is not None)

vol = StorageVolume(tenant_id=1, name="SAN-01-e2e", mount_path=MOUNT,
                    watch_dirs=["/OUT"], read_only=True)
db.add(vol)
db.flush()
plain, h = generate_agent_token()
agent = AgentNode(tenant_id=1, name="agent-e2e", auth_token_hash=h)
db.add(agent)
db.flush()
job = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                  payload={"volume_id": vol.id, "rel_path": REL},
                  requested_by_user_id=admin.id if admin else None)
job_id = job.id
vol_id = vol.id
db.commit()
print(f"setup: volume={vol_id} agent={agent.id} job={job_id} token={plain[:8]}...")

S = requests.Session()
S.headers["X-Agent-Token"] = plain

# --- heartbeat: deve tornare i volumi del tenant ---
r = S.post(f"{BASE}/agent-api/heartbeat",
           json={"version": "0.1.0", "capabilities": ["probe", "checksum"],
                 "volumes": [{"volume_id": vol_id, "total_gb": 100.0, "free_gb": 50.0}]},
           timeout=30)
check("heartbeat 200", r.status_code == 200)
hb = r.json()
vols = {v["id"]: v for v in hb.get("volumes", [])}
check("heartbeat ritorna il volume", vol_id in vols)

# --- auth negativa: token farlocco -> 401 ---
rbad = requests.post(f"{BASE}/agent-api/jobs/claim",
                     headers={"X-Agent-Token": "token-farlocco"}, timeout=30)
check("token invalido -> 401", rbad.status_code == 401)

# --- claim: deve tornare il nostro job probe ---
r = S.post(f"{BASE}/agent-api/jobs/claim", timeout=30)
check("claim 200", r.status_code == 200)
claimed = r.json().get("job")
check("claim ritorna job probe", claimed and claimed["id"] == job_id and claimed["type"] == "probe")

# --- probe locale (lato agent) ---
probe = build_probe_result(vols[vol_id]["mount_path"], claimed["payload"]["rel_path"])
check("probe checksum xxh64 16 char", len(probe.get("checksum_xxhash", "")) == 16)
check("probe file_size = 47", probe.get("file_size") == 47)

# --- post result done -> nasce la proposta ---
r = S.post(f"{BASE}/agent-api/jobs/{job_id}/result",
           json={"status": "done", "result": probe}, timeout=30)
check("post result 200", r.status_code == 200)
asset_id = r.json().get("asset_id")
check("result ritorna asset_id", asset_id is not None)

# --- verifica proposta nel DB ---
db.expire_all()
a = db.get(Asset, asset_id) if asset_id else None
check("asset esiste", a is not None)
if a:
    check("proposed_state = pending_review", a.proposed_state == AssetProposedState.pending_review)
    check("checksum salvato", a.checksum_xxhash == probe["checksum_xxhash"])
    check("file_path marker agent://", a.file_path == f"agent://{vol_id}/{REL}")
    check("rel_path salvato", a.rel_path == REL)
    check("storage_volume_id linkato", a.storage_volume_id == vol_id)

# --- idempotenza/dedup: ri-probe stesso checksum+volume -> stesso asset ---
job2 = enqueue_job(db, tenant_id=1, type=AgentJobType.probe,
                   payload={"volume_id": vol_id, "rel_path": REL},
                   requested_by_user_id=admin.id if admin else None)
db.commit()
S.post(f"{BASE}/agent-api/jobs/claim", timeout=30)  # claim job2
r = S.post(f"{BASE}/agent-api/jobs/{job2.id}/result",
           json={"status": "done", "result": probe}, timeout=30)
check("dedup: stesso asset_id", r.json().get("asset_id") == asset_id)

# --- cleanup E2E (volume/agent/job/asset di test) ---
db.expire_all()
for jj in db.query(AgentJob).filter(AgentJob.id.in_([job_id, job2.id])).all():
    db.delete(jj)
if a:
    db.delete(a)
db.delete(db.get(AgentNode, agent.id))
db.delete(db.get(StorageVolume, vol_id))
db.commit()
print("cleanup E2E fatto")

passed = sum(1 for _, ok in results if ok)
total = len(results)
print(f"\n=== E2E F1: {passed}/{total} ===")
sys.exit(0 if passed == total else 1)
