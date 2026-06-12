"""E2E offline F5 — TransferOrder: manual + aspera mocked end-to-end.

TestClient + DB in-memory: manual create→close→done (2 movimenti outgest, link),
aspera create→claim→handle_job (subprocess mockato rc=0)→post result→done,
aspera failure (rc=1)→failed→notifica, asset non registrato su aspera→400,
transition cancelled, filtro GET ?status=done.
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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
role = Role(
    tenant_id=1,
    code="admin",
    name="Admin",
    permissions=["edit_planning_all", "view_finance", "assign_resources"],
    is_system=True,
    is_active=True,
)
session.add(role)
session.flush()
session.add(
    User(
        tenant_id=1,
        email="admin@test.local",
        full_name="Admin",
        hashed_password="x",
        role=UserRole.admin,
        role_id=role.id,
        is_active=True,
    )
)
session.commit()


def _ovr():
    yield session


main_mod.app.dependency_overrides[get_db] = _ovr
tok = create_access_token({"sub": "admin@test.local", "tid": 1})


# ── Seed: volume + asset registrati + asset non registrato ────────────────────

with TestClient(
    main_mod.app,
    headers={"Cookie": f"access_token={tok}"},
    follow_redirects=False,
) as c:

    # Crea una tmp dir reale da usare come mount_path (i file aspera dovranno esistere)
    tmp_dir = tempfile.mkdtemp(prefix="e2e_f5_vol_")

    # File reali nella tmp dir (run_transfer fa os.path.isfile)
    file1_path = os.path.join(tmp_dir, "master_ep01.mxf")
    file2_path = os.path.join(tmp_dir, "proxy_ep01.mp4")
    with open(file1_path, "wb") as f:
        f.write(b"FAKE MXF CONTENT")
    with open(file2_path, "wb") as f:
        f.write(b"FAKE MP4 CONTENT")

    print("-- Seed: POST /storage/api/volumes --")
    r_vol = c.post(
        "/storage/api/volumes",
        data={"name": "SAN-E2E", "mount_path": tmp_dir, "read_only": "false"},
    )
    check("crea volume 200", r_vol.status_code == 200, str(r_vol.text))
    vol_id = r_vol.json().get("id")
    check("volume_id presente", vol_id is not None, str(r_vol.json()))

    print("-- Seed: POST /storage/api/agents (ottieni token) --")
    r_agent = c.post("/storage/api/agents", data={"name": "Agent-E2E-F5"})
    check("crea agent 200", r_agent.status_code == 200, str(r_agent.text))
    agent_token = r_agent.json().get("token")
    check("agent token presente", agent_token is not None, str(r_agent.json()))

    print("-- Seed: 2 Asset registrati (storage_volume_id + rel_path) --")
    from app.models.models import Asset, AssetProposedState

    asset1 = Asset(
        tenant_id=1,
        filename="master_ep01.mxf",
        original_name="master_ep01.mxf",
        file_path=file1_path,
        file_size=16,
        mime_type="video/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol_id,
        rel_path="master_ep01.mxf",
        proposed_state=AssetProposedState.confirmed,
    )
    asset2 = Asset(
        tenant_id=1,
        filename="proxy_ep01.mp4",
        original_name="proxy_ep01.mp4",
        file_path=file2_path,
        file_size=16,
        mime_type="video/mp4",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol_id,
        rel_path="proxy_ep01.mp4",
        proposed_state=AssetProposedState.confirmed,
    )
    # Asset NON registrato (senza volume/rel_path) — per test step 5
    asset_no_vol = Asset(
        tenant_id=1,
        filename="unregistered.mov",
        original_name="unregistered.mov",
        file_path="",
        file_size=100,
        mime_type="video/quicktime",
        asset_type=AssetType.video,
        uploaded_by=1,
    )
    session.add_all([asset1, asset2, asset_no_vol])
    session.commit()
    session.refresh(asset1)
    session.refresh(asset2)
    session.refresh(asset_no_vol)
    aid1, aid2, aid_no_vol = asset1.id, asset2.id, asset_no_vol.id
    check("asset1 id presente", aid1 is not None)
    check("asset2 id presente", aid2 is not None)
    check("asset_no_vol id presente", aid_no_vol is not None)

    # ── Step 2: MANUAL end-to-end ──────────────────────────────────────────────

    print("-- Step 2a: POST /storage/api/transfers (manual, 2 asset) --")
    r_manual = c.post(
        "/storage/api/transfers",
        data={
            "tool": "manual",
            "asset_ids": f"{aid1},{aid2}",
            "destination": "Backlot S3 share",
            "recipient_email": "client@example.com",
            "note": "E2E test manual",
        },
    )
    check("crea ordine manual 200", r_manual.status_code == 200, str(r_manual.text))
    manual_order_id = r_manual.json().get("id")
    check("manual order_id presente", manual_order_id is not None, str(r_manual.json()))

    print("-- Step 2b: POST /storage/api/transfers/{id}/close (ok=true, link) --")
    r_close = c.post(
        f"/storage/api/transfers/{manual_order_id}/close",
        data={
            "ok": "true",
            "method": "manual",
            "link_url": "https://example.com/dl/abc",
            "link_expires_at": "2026-12-31",
        },
    )
    check("close manual → 200", r_close.status_code == 200, str(r_close.text))
    check("status==done (close resp)", r_close.json().get("status") == "done",
          str(r_close.json()))

    print("-- Step 2c: verifica 2 AssetMovement outgest in DB --")
    from app.models.models import AssetMovement, AssetMovementType
    session.expire_all()
    movements = session.query(AssetMovement).filter(
        AssetMovement.tenant_id == 1,
        AssetMovement.movement_type == AssetMovementType.outgest,
    ).all()
    check("2 movimenti outgest in DB", len(movements) == 2,
          f"got={len(movements)}")
    if len(movements) >= 1:
        mv = movements[0]
        check("to_party == destination", mv.to_party == "Backlot S3 share",
              f"to_party={mv.to_party}")
        check("carrier == 'manual'", mv.carrier == "manual",
              f"carrier={mv.carrier}")
        check("tracking_number contiene link",
              (mv.tracking_number or "").startswith("https://example.com/dl/"),
              f"tracking={mv.tracking_number}")
        check("contents_description contiene 'TransferOrder'",
              "TransferOrder" in (mv.contents_description or ""),
              f"desc={mv.contents_description}")

    print("-- Step 2d: GET /storage/api/transfers → ordine con link_url e status done --")
    r_list_done = c.get("/storage/api/transfers", params={"status": "done"})
    check("GET transfers done 200", r_list_done.status_code == 200, str(r_list_done.text))
    done_orders = r_list_done.json()
    manual_found = next((o for o in done_orders if o["id"] == manual_order_id), None)
    check("ordine manual presente in lista done", manual_found is not None,
          f"ids={[o['id'] for o in done_orders]}")
    if manual_found:
        check("link_url presente nella risposta",
              manual_found.get("link_url") == "https://example.com/dl/abc",
              f"link_url={manual_found.get('link_url')}")
        check("status==done nella lista", manual_found.get("status") == "done",
              f"status={manual_found.get('status')}")
        check("assets contiene 2 entry",
              len(manual_found.get("assets", [])) == 2,
              f"assets={manual_found.get('assets')}")

    # ── Step 3: ASPERA mocked ok ───────────────────────────────────────────────

    print("-- Step 3a: POST /storage/api/transfers (aspera, 2 asset registrati) --")
    r_aspera = c.post(
        "/storage/api/transfers",
        data={
            "tool": "aspera",
            "asset_ids": f"{aid1},{aid2}",
            "destination": "asperauser@aspera.example.com:/ingest/e2e",
            "recipient_email": "ops@facility.it",
        },
    )
    check("crea ordine aspera 200", r_aspera.status_code == 200, str(r_aspera.text))
    aspera_order_id = r_aspera.json().get("id")
    check("aspera order_id presente", aspera_order_id is not None, str(r_aspera.json()))

    # Verifica AgentJob di tipo transfer in coda
    session.expire_all()
    from app.models.models import AgentJob, AgentJobType as AJT
    from sqlalchemy import select as sa_select
    aspera_job = session.execute(
        sa_select(AgentJob).where(
            AgentJob.tenant_id == 1,
            AgentJob.type == AJT.transfer,
        ).order_by(AgentJob.id.desc()).limit(1)
    ).scalar_one_or_none()
    check("AgentJob transfer in coda", aspera_job is not None)
    if aspera_job:
        payload = aspera_job.payload or {}
        check("payload tool==aspera", payload.get("tool") == "aspera",
              f"tool={payload.get('tool')}")
        check("payload files×2", len(payload.get("files", [])) == 2,
              f"files={payload.get('files')}")
        check("payload destination presente",
              bool(payload.get("destination")),
              f"destination={payload.get('destination')}")

    print("-- Step 3b: claim job con agent token --")
    r_claim = c.post(
        "/agent-api/jobs/claim",
        headers={"X-Agent-Token": agent_token},
    )
    check("claim 200", r_claim.status_code == 200, str(r_claim.text))
    claimed_job = r_claim.json().get("job")
    check("job claimato presente", claimed_job is not None, str(r_claim.json()))
    if claimed_job:
        check("job type == transfer", claimed_job.get("type") == "transfer",
              f"type={claimed_job.get('type')}")
    claimed_job_id = (claimed_job or {}).get("id")

    print("-- Step 3c: handle_job con subprocess mockato (rc=0) --")

    import agent.transfer as tmod

    # Monkeypatch shutil.which e subprocess.run — ripristino in try/finally
    orig_which = tmod.shutil.which
    orig_run = tmod.subprocess.run

    def stub_run_ok(*args, **kwargs):
        result = types.SimpleNamespace()
        result.returncode = 0
        result.stdout = "FASP Completed"
        result.stderr = ""
        return result

    try:
        tmod.shutil.which = lambda x: "C:/fake/ascp.exe"
        tmod.subprocess.run = stub_run_ok

        # Costruiamo volumes_by_id con il volume reale (mount_path = tmp_dir reale)
        volumes_by_id = {vol_id: {"mount_path": tmp_dir}}

        from agent.main import handle_job
        claimed_payload = (claimed_job or {}).get("payload") or aspera_job.payload
        job_dict = {"id": claimed_job_id or aspera_job.id,
                    "type": "transfer",
                    "payload": claimed_payload}
        status_agent, result_agent, error_agent = handle_job(
            job_dict, volumes_by_id, watch_states={},
        )
    finally:
        tmod.shutil.which = orig_which
        tmod.subprocess.run = orig_run

    check("handle_job status==done (aspera ok)", status_agent == "done",
          f"status={status_agent} error={error_agent}")
    check("result ok==True", (result_agent or {}).get("ok") is True,
          f"result={result_agent}")
    check("result files==2", (result_agent or {}).get("files") == 2,
          f"files={(result_agent or {}).get('files')}")

    print("-- Step 3d: POST /agent-api/jobs/{id}/result → ordine done + 2 nuovi movimenti --")
    r_result = c.post(
        f"/agent-api/jobs/{claimed_job_id or aspera_job.id}/result",
        json={"status": status_agent, "result": result_agent, "error": error_agent},
        headers={"X-Agent-Token": agent_token},
    )
    check("post result aspera ok 200", r_result.status_code == 200, str(r_result.text))

    # Verifica ordine aspera done
    session.expire_all()
    from app.models.models import TransferOrder
    aspera_order = session.get(TransferOrder, aspera_order_id)
    check("ordine aspera status==done", (aspera_order and aspera_order.status) == "done",
          f"status={getattr(aspera_order, 'status', None)}")

    # Verifica nuovi movimenti outgest per aspera (ora total = 4: 2 manual + 2 aspera)
    all_movements = session.query(AssetMovement).filter(
        AssetMovement.tenant_id == 1,
        AssetMovement.movement_type == AssetMovementType.outgest,
    ).all()
    check("4 movimenti outgest totali dopo aspera", len(all_movements) == 4,
          f"got={len(all_movements)}")

    # ── Step 4: ASPERA failure ─────────────────────────────────────────────────

    print("-- Step 4a: POST /storage/api/transfers (aspera 2) per test failure --")
    r_aspera2 = c.post(
        "/storage/api/transfers",
        data={
            "tool": "aspera",
            "asset_ids": f"{aid1},{aid2}",
            "destination": "asperauser@aspera.example.com:/ingest/fail",
        },
    )
    check("crea ordine aspera2 200", r_aspera2.status_code == 200, str(r_aspera2.text))
    aspera_order2_id = r_aspera2.json().get("id")

    # claim job aspera2
    r_claim2 = c.post(
        "/agent-api/jobs/claim",
        headers={"X-Agent-Token": agent_token},
    )
    check("claim aspera2 200", r_claim2.status_code == 200, str(r_claim2.text))
    claimed_job2 = r_claim2.json().get("job")
    check("job2 claimato", claimed_job2 is not None, str(r_claim2.json()))
    claimed_job2_id = (claimed_job2 or {}).get("id")

    print("-- Step 4b: handle_job con stub rc=1 (auth failed) --")

    def stub_run_fail(*args, **kwargs):
        result = types.SimpleNamespace()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "auth failed: invalid credentials"
        return result

    orig_which2 = tmod.shutil.which
    orig_run2 = tmod.subprocess.run
    try:
        tmod.shutil.which = lambda x: "C:/fake/ascp.exe"
        tmod.subprocess.run = stub_run_fail

        volumes_by_id2 = {vol_id: {"mount_path": tmp_dir}}
        claimed_payload2 = (claimed_job2 or {}).get("payload") or {}
        job_dict2 = {"id": claimed_job2_id,
                     "type": "transfer",
                     "payload": claimed_payload2}
        status2, result2, error2 = handle_job(job_dict2, volumes_by_id2, watch_states={})
    finally:
        tmod.shutil.which = orig_which2
        tmod.subprocess.run = orig_run2

    check("handle_job status==failed (rc=1)", status2 == "failed",
          f"status={status2}")
    check("error contiene 'auth failed'", "auth failed" in (error2 or ""),
          f"error={error2}")

    print("-- Step 4c: POST /agent-api/jobs/{id}/result (failed) --")
    r_result2 = c.post(
        f"/agent-api/jobs/{claimed_job2_id}/result",
        json={"status": "failed", "result": None, "error": error2},
        headers={"X-Agent-Token": agent_token},
    )
    check("post result failed 200", r_result2.status_code == 200, str(r_result2.text))

    # Verifica ordine fallito
    session.expire_all()
    aspera_order2 = session.get(TransferOrder, aspera_order2_id)
    check("ordine aspera2 status==failed",
          (aspera_order2 and aspera_order2.status) == "failed",
          f"status={getattr(aspera_order2, 'status', None)}")

    # Verifica notifica "Transfer fallito" in tabella notifications
    from app.models.models import Notification
    notifs_fail = session.query(Notification).filter(
        Notification.tenant_id == 1,
        Notification.title.contains("Transfer fallito"),
    ).all()
    check("notifica 'Transfer fallito' presente", len(notifs_fail) >= 1,
          f"notifiche trovate={len(notifs_fail)}")

    # ── Step 5: Aspera con asset non registrato → 400 ─────────────────────────

    print("-- Step 5: aspera con asset senza storage_volume_id → 400 --")
    r_bad = c.post(
        "/storage/api/transfers",
        data={
            "tool": "aspera",
            "asset_ids": str(aid_no_vol),
            "destination": "asperauser@aspera.example.com:/ingest/bad",
        },
    )
    check("aspera asset non registrato → 400", r_bad.status_code == 400,
          f"status={r_bad.status_code} body={r_bad.text}")

    # ── Step 6: Transition cancelled + GET filtro done ─────────────────────────

    print("-- Step 6a: crea ordine manual nuovo poi → cancelled --")
    r_new = c.post(
        "/storage/api/transfers",
        data={
            "tool": "manual",
            "asset_ids": str(aid1),
            "destination": "To be cancelled",
        },
    )
    check("crea ordine da cancellare 200", r_new.status_code == 200, str(r_new.text))
    cancel_order_id = r_new.json().get("id")

    r_cancel = c.post(
        f"/storage/api/transfers/{cancel_order_id}/transition",
        data={"status": "cancelled"},
    )
    check("→ cancelled 200", r_cancel.status_code == 200, str(r_cancel.text))
    check("status==cancelled", r_cancel.json().get("status") == "cancelled",
          str(r_cancel.json()))

    print("-- Step 6b: GET /storage/api/transfers?status=done → contiene i done --")
    r_done_filter = c.get("/storage/api/transfers", params={"status": "done"})
    check("GET ?status=done 200", r_done_filter.status_code == 200,
          str(r_done_filter.text))
    done_list = r_done_filter.json()
    done_ids_set = {o["id"] for o in done_list}
    check("ordine manual done presente", manual_order_id in done_ids_set,
          f"done_ids={done_ids_set}")
    check("ordine aspera done presente", aspera_order_id in done_ids_set,
          f"done_ids={done_ids_set}")
    check("ordine cancelled NON in lista done", cancel_order_id not in done_ids_set,
          f"cancelled_id={cancel_order_id} in done_ids={done_ids_set}")

# ── Cleanup ────────────────────────────────────────────────────────────────────

main_mod.app.dependency_overrides.pop(get_db, None)
session.close()

# Rimuovi file tmp
import shutil as _shutil
try:
    _shutil.rmtree(tmp_dir, ignore_errors=True)
except Exception:
    pass

# ── Report finale ──────────────────────────────────────────────────────────────

failed = [n for n, ok in OK if not ok]
print(f"\n{len(OK) - len(failed)}/{len(OK)} check passati")
sys.exit(1 if failed else 0)
