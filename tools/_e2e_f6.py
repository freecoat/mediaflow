"""E2E offline F6 — Distruzione asset doppia-conferma + agent verify +
asset-map + lockdown transfer.

TestClient + DB in-memory, due utenti (A richiedente, B approvatore) con
cookie distinti:
  - asset con file vero su tmp dir reale (volume mount_path)
  - distruzione: request (A) → approve self (A) 400 → approve (B) 200
  - enqueue-verify → claim agent → handle_job (file PRESENTE) → result →
    resta approved + notifica al richiedente
  - cancella file → secondo enqueue-verify → handle_job (ASSENTE) → result →
    done + AssetMovement destroyed + content_state deleted
  - variante membership tape → archived_only via execute-manual
  - asset-map riflette deleted + destruction_pending False (chiusa)
  - storage-report: pending.destructions_open + content_states
  - lockdown transfer: whitelist → non-whitelistato 403, whitelistato 200
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, AssetType
from app.models import User, Role, Tenant
from app.models.models import UserRole
from app.services.auth import create_access_token

import app.database as database
import app.main as main_mod
from app.database import get_db

# ── Contatori check ────────────────────────────────────────────────────────────

OK = []


def check(name, cond, detail=""):
    OK.append((name, bool(cond)))
    marker = "  OK " if cond else "  FAIL "
    line = marker + name
    if detail and not cond:
        line += f"  [{detail}]"
    print(line)


# ── DB in-memory ───────────────────────────────────────────────────────────────

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
database.engine = engine
database.SessionLocal = TestSession
session = TestSession()

session.add(Tenant(id=1, name="T", slug="t1", is_active=True))
session.flush()

# Ruolo con approve_destruction (TPN) per entrambi gli utenti
role = Role(
    tenant_id=1,
    code="admin",
    name="Admin",
    permissions=[
        "edit_planning_all", "view_finance", "assign_resources",
        "approve_destruction", "manage_cloud_lockdown", "manage_roles",
    ],
    is_system=True,
    is_active=True,
)
session.add(role)
session.flush()

# Utente A — richiedente
user_a = User(
    tenant_id=1,
    email="a@test.local",
    full_name="Utente A",
    hashed_password="x",
    role=UserRole.admin,
    role_id=role.id,
    is_active=True,
)
# Utente B — approvatore (diverso dal richiedente)
user_b = User(
    tenant_id=1,
    email="b@test.local",
    full_name="Utente B",
    hashed_password="x",
    role=UserRole.admin,
    role_id=role.id,
    is_active=True,
)
session.add_all([user_a, user_b])
session.commit()
session.refresh(user_a)
session.refresh(user_b)
uid_a, uid_b = user_a.id, user_b.id


def _ovr():
    yield session


main_mod.app.dependency_overrides[get_db] = _ovr
tok_a = create_access_token({"sub": "a@test.local", "tid": 1})
tok_b = create_access_token({"sub": "b@test.local", "tid": 1})


# ── Due TestClient con cookie distinti ──────────────────────────────────────────

with TestClient(
    main_mod.app,
    headers={"Cookie": f"access_token={tok_a}"},
    follow_redirects=False,
) as ca, TestClient(
    main_mod.app,
    headers={"Cookie": f"access_token={tok_b}"},
    follow_redirects=False,
) as cb:

    # tmp dir reale come volume; 2 file veri
    tmp_dir = tempfile.mkdtemp(prefix="e2e_f6_vol_")
    file1_path = os.path.join(tmp_dir, "master_ep01.mxf")
    file2_path = os.path.join(tmp_dir, "archived_ep02.mxf")
    with open(file1_path, "wb") as f:
        f.write(b"FAKE MXF CONTENT 1")
    with open(file2_path, "wb") as f:
        f.write(b"FAKE MXF CONTENT 2")

    print("-- Seed: POST /storage/api/volumes --")
    r_vol = ca.post(
        "/storage/api/volumes",
        data={"name": "SAN-E2E-F6", "mount_path": tmp_dir, "read_only": "false"},
    )
    check("crea volume 200", r_vol.status_code == 200, str(r_vol.text))
    vol_id = r_vol.json().get("id")
    check("volume_id presente", vol_id is not None, str(r_vol.json()))

    print("-- Seed: POST /storage/api/agents (token) --")
    r_agent = ca.post("/storage/api/agents", data={"name": "Agent-E2E-F6"})
    check("crea agent 200", r_agent.status_code == 200, str(r_agent.text))
    agent_token = r_agent.json().get("token")
    check("agent token presente", agent_token is not None, str(r_agent.json()))

    print("-- Seed: 2 Asset registrati confermati --")
    from app.models.models import Asset, AssetProposedState

    asset1 = Asset(
        tenant_id=1,
        filename="master_ep01.mxf",
        original_name="master_ep01.mxf",
        file_path=file1_path,
        file_size=18,
        mime_type="video/mxf",
        asset_type=AssetType.video,
        uploaded_by=uid_a,
        storage_volume_id=vol_id,
        rel_path="master_ep01.mxf",
        proposed_state=AssetProposedState.confirmed,
    )
    asset2 = Asset(
        tenant_id=1,
        filename="archived_ep02.mxf",
        original_name="archived_ep02.mxf",
        file_path=file2_path,
        file_size=18,
        mime_type="video/mxf",
        asset_type=AssetType.video,
        uploaded_by=uid_a,
        storage_volume_id=vol_id,
        rel_path="archived_ep02.mxf",
        proposed_state=AssetProposedState.confirmed,
    )
    session.add_all([asset1, asset2])
    session.commit()
    session.refresh(asset1)
    session.refresh(asset2)
    aid1, aid2 = asset1.id, asset2.id
    check("asset1 id presente", aid1 is not None)
    check("asset2 id presente", aid2 is not None)

    # ── Step 1: request (A) ────────────────────────────────────────────────────

    print("-- Step 1: POST /storage/api/destructions (client A) --")
    r_req = ca.post(
        "/storage/api/destructions",
        data={"asset_id": aid1, "reason": "Fine progetto — TPN audit"},
    )
    check("crea distruzione 200", r_req.status_code == 200, str(r_req.text))
    req_id = r_req.json().get("id")
    check("request_id presente", req_id is not None, str(r_req.json()))

    # ── Step 2: doppia conferma ────────────────────────────────────────────────

    print("-- Step 2a: approve con stesso richiedente (A) → 400 --")
    r_self = ca.post(f"/storage/api/destructions/{req_id}/approve")
    check("self-approval → 400", r_self.status_code == 400,
          f"status={r_self.status_code} body={r_self.text}")

    print("-- Step 2b: approve con utente diverso (B) → 200 approved --")
    r_appr = cb.post(f"/storage/api/destructions/{req_id}/approve")
    check("approve (B) → 200", r_appr.status_code == 200, str(r_appr.text))
    check("status==approved", r_appr.json().get("status") == "approved",
          str(r_appr.json()))
    session.expire_all()
    from app.models.models import DestructionRequest
    req_db = session.get(DestructionRequest, req_id)
    check("approved_by == B", req_db.approved_by_user_id == uid_b,
          f"approved_by={req_db.approved_by_user_id}")
    check("requested_by == A", req_db.requested_by_user_id == uid_a,
          f"requested_by={req_db.requested_by_user_id}")

    # ── Step 3: enqueue-verify #1 (file ANCORA presente) ───────────────────────

    print("-- Step 3a: enqueue-verify (B) → AgentJob delete_verify --")
    r_eq1 = cb.post(f"/storage/api/destructions/{req_id}/enqueue-verify")
    check("enqueue-verify 200", r_eq1.status_code == 200, str(r_eq1.text))
    job_id1 = r_eq1.json().get("job_id")
    check("job_id presente", isinstance(job_id1, int), str(r_eq1.json()))

    session.expire_all()
    from app.models.models import AgentJob, AgentJobType as AJT
    job1 = session.get(AgentJob, job_id1)
    check("AgentJob type==delete_verify", job1 and job1.type == AJT.delete_verify,
          f"type={getattr(job1, 'type', None)}")
    check("payload request_id corretto",
          (job1.payload or {}).get("request_id") == req_id,
          f"payload={getattr(job1, 'payload', None)}")

    print("-- Step 3b: claim job con agent token --")
    r_claim1 = ca.post("/agent-api/jobs/claim", headers={"X-Agent-Token": agent_token})
    check("claim 200", r_claim1.status_code == 200, str(r_claim1.text))
    claimed1 = r_claim1.json().get("job")
    check("job claimato", claimed1 is not None, str(r_claim1.json()))
    check("claim type==delete_verify",
          (claimed1 or {}).get("type") == "delete_verify",
          f"type={(claimed1 or {}).get('type')}")

    print("-- Step 3c: handle_job con file ANCORA presente → exists True --")
    from agent.main import handle_job
    volumes_by_id = {vol_id: {"mount_path": tmp_dir}}
    job_dict1 = {"id": job_id1, "type": "delete_verify",
                 "payload": (claimed1 or {}).get("payload") or (job1.payload or {})}
    st1, res1, err1 = handle_job(job_dict1, volumes_by_id, watch_states={})
    check("handle_job status==done", st1 == "done", f"status={st1} err={err1}")
    check("result exists==True (file presente)", (res1 or {}).get("exists") is True,
          f"result={res1}")

    print("-- Step 3d: POST result → richiesta resta approved + notifica --")
    r_res1 = ca.post(
        f"/agent-api/jobs/{job_id1}/result",
        json={"status": st1, "result": res1, "error": err1},
        headers={"X-Agent-Token": agent_token},
    )
    check("post result 200", r_res1.status_code == 200, str(r_res1.text))
    session.expire_all()
    req_db = session.get(DestructionRequest, req_id)
    check("richiesta ancora approved", req_db.status == "approved",
          f"status={req_db.status}")

    from app.models.models import Notification
    notifs_present = session.execute(
        select(Notification).where(
            Notification.tenant_id == 1,
            Notification.user_id == uid_a,
            Notification.title.contains("ancora presente"),
        )
    ).scalars().all()
    check("notifica 'ancora presente' al richiedente", len(notifs_present) >= 1,
          f"trovate={len(notifs_present)}")

    # ── Step 4: cancella file vero → verify #2 (ASSENTE) → done ────────────────

    print("-- Step 4a: cancella file vero dal disco --")
    os.remove(file1_path)
    check("file rimosso dal disco", not os.path.isfile(file1_path))

    print("-- Step 4b: secondo enqueue-verify → claim → handle_job exists False --")
    r_eq2 = cb.post(f"/storage/api/destructions/{req_id}/enqueue-verify")
    check("enqueue-verify #2 200", r_eq2.status_code == 200, str(r_eq2.text))
    job_id2 = r_eq2.json().get("job_id")

    r_claim2 = ca.post("/agent-api/jobs/claim", headers={"X-Agent-Token": agent_token})
    check("claim #2 200", r_claim2.status_code == 200, str(r_claim2.text))
    claimed2 = r_claim2.json().get("job")
    session.expire_all()
    job2 = session.get(AgentJob, job_id2)
    job_dict2 = {"id": job_id2, "type": "delete_verify",
                 "payload": (claimed2 or {}).get("payload") or (job2.payload or {})}
    st2, res2, err2 = handle_job(job_dict2, volumes_by_id, watch_states={})
    check("handle_job #2 status==done", st2 == "done", f"status={st2} err={err2}")
    check("result exists==False (file assente)", (res2 or {}).get("exists") is False,
          f"result={res2}")

    print("-- Step 4c: POST result → done + movimento destroyed + content_state deleted --")
    r_res2 = ca.post(
        f"/agent-api/jobs/{job_id2}/result",
        json={"status": st2, "result": res2, "error": err2},
        headers={"X-Agent-Token": agent_token},
    )
    check("post result #2 200", r_res2.status_code == 200, str(r_res2.text))

    session.expire_all()
    req_db = session.get(DestructionRequest, req_id)
    check("richiesta done", req_db.status == "done", f"status={req_db.status}")

    from app.models.models import (
        AssetMovement, AssetMovementType, AssetContentState,
    )
    movs = session.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == aid1,
            AssetMovement.movement_type == AssetMovementType.destroyed,
        )
    ).scalars().all()
    check("1 AssetMovement destroyed", len(movs) == 1, f"got={len(movs)}")

    asset1_db = session.get(Asset, aid1)
    check("content_state == deleted (no tape)",
          asset1_db.content_state == AssetContentState.deleted,
          f"content_state={asset1_db.content_state}")

    # ── Step 5: variante membership tape → archived_only (execute-manual) ──────

    print("-- Step 5: secondo asset con membership LTO attiva → archived_only --")
    from app.models.models import (
        PhysicalAsset, PhysicalAssetKind, AssetOwnerType, AssetMembership,
    )
    tape = PhysicalAsset(
        tenant_id=1,
        kind=PhysicalAssetKind.lto,
        label="LTO #F6 - Test",
        owner_type=AssetOwnerType.internal,
        is_internal_archive=True,
        logistics_status="in_storage",
        qr_code_token="f6tapetoken",
    )
    session.add(tape)
    session.flush()
    session.add(AssetMembership(
        tenant_id=1, physical_asset_id=tape.id, asset_id=aid2,
        file_size=asset2.file_size,
    ))
    session.commit()

    r_req2 = ca.post(
        "/storage/api/destructions",
        data={"asset_id": aid2, "reason": "Distruzione su SAN, copia su LTO"},
    )
    check("crea distruzione asset2 200", r_req2.status_code == 200, str(r_req2.text))
    req2_id = r_req2.json().get("id")

    r_appr2 = cb.post(f"/storage/api/destructions/{req2_id}/approve")
    check("approve asset2 (B) 200", r_appr2.status_code == 200, str(r_appr2.text))

    r_exec = cb.post(f"/storage/api/destructions/{req2_id}/execute-manual")
    check("execute-manual 200", r_exec.status_code == 200, str(r_exec.text))
    check("execute-manual status==done", r_exec.json().get("status") == "done",
          str(r_exec.json()))

    session.expire_all()
    asset2_db = session.get(Asset, aid2)
    check("content_state == archived_only (tape attiva)",
          asset2_db.content_state == AssetContentState.archived_only,
          f"content_state={asset2_db.content_state}")

    # ── Step 6: asset-map riflette deleted + destruction chiusa ────────────────

    print("-- Step 6: GET /storage/api/asset-map --")
    r_map = ca.get("/storage/api/asset-map")
    check("asset-map 200", r_map.status_code == 200, str(r_map.text))
    map_body = r_map.json()
    by_id = {i["id"]: i for i in map_body.get("items", [])}
    a1m = by_id.get(aid1)
    check("asset1 presente in asset-map", a1m is not None, str(list(by_id.keys())))
    if a1m:
        check("asset1 content_state==deleted",
              a1m.get("content_state") == "deleted",
              f"content_state={a1m.get('content_state')}")
        check("asset1 destruction_pending False (chiusa)",
              a1m.get("destruction_pending") is False,
              f"destruction_pending={a1m.get('destruction_pending')}")
    a2m = by_id.get(aid2)
    if a2m:
        check("asset2 content_state==archived_only",
              a2m.get("content_state") == "archived_only",
              f"content_state={a2m.get('content_state')}")

    # ── Step 7: storage-report ─────────────────────────────────────────────────

    print("-- Step 7: GET /storage/api/storage-report --")
    r_rep = ca.get("/storage/api/storage-report")
    check("storage-report 200", r_rep.status_code == 200, str(r_rep.text))
    rep = r_rep.json()
    check("report ha pending", "pending" in rep, str(list(rep.keys())))
    check("destructions_open == 0 (tutte chiuse)",
          rep.get("pending", {}).get("destructions_open") == 0,
          f"destructions_open={rep.get('pending', {}).get('destructions_open')}")
    cs = rep.get("content_states", {})
    check("content_states conta deleted >= 1", cs.get("deleted", 0) >= 1, f"cs={cs}")
    check("content_states conta archived_only >= 1",
          cs.get("archived_only", 0) >= 1, f"cs={cs}")

    # ── Step 8: lockdown transfer whitelist ────────────────────────────────────

    print("-- Step 8: set lockdown + whitelist; transfer gate 403/200 --")
    tnt = session.get(Tenant, 1)
    tnt.lockdown_master = "LOCKDOWN"
    tnt.transfer_destination_whitelist = ["aspera.netflix.com"]
    session.commit()

    # File vero per asset2 esiste ancora → transfer aspera valido lato agent path
    r_bad = ca.post(
        "/storage/api/transfers",
        data={
            "tool": "aspera",
            "asset_ids": str(aid2),
            "destination": "user@evil.com:/x",
        },
    )
    check("transfer non whitelistato → 403", r_bad.status_code == 403,
          f"status={r_bad.status_code} body={r_bad.text}")

    r_good = ca.post(
        "/storage/api/transfers",
        data={
            "tool": "aspera",
            "asset_ids": str(aid2),
            "destination": "user@aspera.netflix.com:/in",
        },
    )
    check("transfer whitelistato → 200", r_good.status_code == 200,
          f"status={r_good.status_code} body={r_good.text}")

# ── Cleanup ────────────────────────────────────────────────────────────────────

main_mod.app.dependency_overrides.pop(get_db, None)
session.close()

import shutil as _shutil
try:
    _shutil.rmtree(tmp_dir, ignore_errors=True)
except Exception:
    pass

# ── Report finale ──────────────────────────────────────────────────────────────

failed = [n for n, ok in OK if not ok]
print(f"\n{len(OK) - len(failed)}/{len(OK)} check passati")
sys.exit(1 if failed else 0)
