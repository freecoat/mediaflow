# tests/test_f6_destruction.py
"""F6 (spec 2026-06-12) — Service destruction: doppia conferma, FSM, finalize,
agent delete_verify + wiring process_job_result.

Gruppi (piano Task 2):
  1. request_destruction (notify_permission, reason vuota, doppia richiesta attiva)
  2. approve (richiedente==approvatore vietato)
  3. reject (da requested ok, da approved no)
  4. execute_manual finalize (movimento destroyed, deleted vs archived_only, notifica)
  5. execute_manual da requested → ValueError
  6. enqueue_verify (AgentJob delete_verify, asset non registrato → ValueError)
  7. apply_verify_result (exists False → finalize; True → resta approved + notifica)
  8. cancelled da requested/approved; terminali immutabili
+ agent handle_job delete_verify (exists, traversal, CAPABILITIES)
+ wiring POST /agent-api/jobs/{id}/result (done/failed)
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base,
    AgentJob, AgentJobType,
    Asset, AssetType, AssetContentState,
    AssetMembership, AssetMovement, AssetMovementType,
    DestructionRequest,
    PhysicalAsset, PhysicalAssetKind,
    StorageVolume,
)
import app.services.destruction as svc_mod
from app.services.destruction import (
    request_destruction, approve, reject, execute_manual,
    enqueue_verify, apply_verify_result, apply_verify_failure, transition,
)


# ── helpers ─────────────────────────────────────────────────────────

def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _asset(db, name="master.mxf", registered=False):
    a = Asset(
        tenant_id=1,
        filename=name,
        original_name=name,
        file_path=f"/san/{name}",
        file_size=1_000_000,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
    )
    if registered:
        vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
        db.add(vol)
        db.flush()
        a.storage_volume_id = vol.id
        a.rel_path = f"OUT/{name}"
    db.add(a)
    db.flush()
    return a


def _lto_membership(db, asset_id, label="LTO #001"):
    pa = PhysicalAsset(tenant_id=1, kind=PhysicalAssetKind.lto, label=label)
    db.add(pa)
    db.flush()
    m = AssetMembership(tenant_id=1, asset_id=asset_id, physical_asset_id=pa.id)
    db.add(m)
    db.flush()
    return m


# ── stub monkeypatching (pattern test_f4_archive_tickets.py) ────────

class _NotifyCalls:
    def __init__(self):
        self.notify_calls = []
        self.notify_permission_calls = []

    def stub_notify(self, db, *, user_ids, kind, title, **kwargs):
        self.notify_calls.append(
            {"user_ids": list(user_ids), "kind": kind, "title": title, **kwargs})
        return []

    def stub_notify_permission(self, db, *, permission, kind, title, **kwargs):
        self.notify_permission_calls.append(
            {"permission": permission, "kind": kind, "title": title, **kwargs})
        return []


@pytest.fixture
def notif():
    calls = _NotifyCalls()
    with (
        patch.object(svc_mod, "notify", calls.stub_notify),
        patch.object(svc_mod, "notify_permission", calls.stub_notify_permission),
    ):
        yield calls


def _approved_request(db, asset=None, requested_by=1, approved_by=2, reason="fine progetto"):
    """Helper: richiesta già approvata."""
    if asset is None:
        asset = _asset(db)
    req = request_destruction(db, asset=asset, reason=reason, user_id=requested_by)
    approve(db, req, user_id=approved_by)
    return req, asset


# ── 1. request_destruction ──────────────────────────────────────────

def test_request_creates_requested_and_notifies_approvers(notif):
    db = _session()
    a = _asset(db)

    req = request_destruction(db, asset=a, reason="fine retention TPN", user_id=7)

    assert req.status == "requested"
    assert req.asset_id == a.id
    assert req.reason == "fine retention TPN"
    assert req.requested_by_user_id == 7
    assert len(notif.notify_permission_calls) == 1
    np = notif.notify_permission_calls[0]
    assert np["permission"] == "approve_destruction"
    assert "master.mxf" in np["title"]


def test_request_empty_reason_raises(notif):
    db = _session()
    a = _asset(db)
    with pytest.raises(ValueError, match="[Rr]eason|[Mm]otivazione"):
        request_destruction(db, asset=a, reason="   ", user_id=1)
    assert notif.notify_permission_calls == []


def test_request_second_active_same_asset_raises(notif):
    db = _session()
    a = _asset(db)
    request_destruction(db, asset=a, reason="r1", user_id=1)

    with pytest.raises(ValueError, match="attiva"):
        request_destruction(db, asset=a, reason="r2", user_id=2)

    # anche con la prima approvata (approved = ancora attiva)
    db2 = _session()
    a2 = _asset(db2)
    req = request_destruction(db2, asset=a2, reason="r1", user_id=1)
    approve(db2, req, user_id=2)
    with pytest.raises(ValueError, match="attiva"):
        request_destruction(db2, asset=a2, reason="r2", user_id=3)


def test_request_after_terminal_ok(notif):
    """Richiesta rejected non blocca una nuova richiesta."""
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r1", user_id=1)
    reject(db, req, user_id=2)

    req2 = request_destruction(db, asset=a, reason="r2", user_id=1)
    assert req2.status == "requested"


# ── 2. approve ──────────────────────────────────────────────────────

def test_approve_same_user_raises(notif):
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=5)

    with pytest.raises(ValueError, match="approvatore diverso"):
        approve(db, req, user_id=5)
    assert req.status == "requested"


def test_approve_other_user_ok(notif):
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=5)

    approve(db, req, user_id=6)

    assert req.status == "approved"
    assert req.approved_by_user_id == 6


def test_approve_from_approved_raises(notif):
    db = _session()
    req, _ = _approved_request(db)
    with pytest.raises(ValueError, match="[Tt]ransizione|requested"):
        approve(db, req, user_id=9)


# ── 3. reject ───────────────────────────────────────────────────────

def test_reject_from_requested_ok(notif):
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=1)

    reject(db, req, user_id=2, reason="asset ancora in delivery")

    assert req.status == "rejected"
    assert req.closed_at is not None
    assert req.closed_by_user_id == 2
    # notifica al richiedente
    assert any(1 in c["user_ids"] for c in notif.notify_calls)


def test_reject_from_approved_raises(notif):
    db = _session()
    req, _ = _approved_request(db)
    with pytest.raises(ValueError):
        reject(db, req, user_id=3)
    assert req.status == "approved"


# ── 4. execute_manual → finalize ────────────────────────────────────

def test_execute_manual_no_membership_deleted(notif):
    db = _session()
    req, a = _approved_request(db, reason="fine retention")

    execute_manual(db, req, user_id=2)

    assert req.status == "done"
    assert req.executed_method == "manual"
    assert req.closed_at is not None
    assert req.closed_by_user_id == 2

    db.expire(a)
    assert db.get(Asset, a.id).content_state == AssetContentState.deleted

    mvs = db.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == a.id,
            AssetMovement.movement_type == AssetMovementType.destroyed)
    ).scalars().all()
    assert len(mvs) == 1
    assert mvs[0].contents_description == "fine retention"

    # notifica al richiedente (user 1)
    assert any(1 in c["user_ids"] and "istru" in c["title"]
               for c in notif.notify_calls)


def test_execute_manual_with_active_tape_archived_only(notif):
    db = _session()
    a = _asset(db)
    _lto_membership(db, a.id)
    req, _ = _approved_request(db, asset=a)

    execute_manual(db, req, user_id=2)

    assert req.status == "done"
    db.expire(a)
    assert db.get(Asset, a.id).content_state == AssetContentState.archived_only
    # movimento creato comunque
    n = db.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == a.id,
            AssetMovement.movement_type == AssetMovementType.destroyed)
    ).scalars().all()
    assert len(n) == 1


def test_execute_manual_with_removed_membership_deleted(notif):
    """Membership rimossa (removed_at valorizzato) NON conta come copia residua."""
    from app.services.clock import now_utc
    db = _session()
    a = _asset(db)
    m = _lto_membership(db, a.id)
    m.removed_at = now_utc()
    db.flush()
    req, _ = _approved_request(db, asset=a)

    execute_manual(db, req, user_id=2)

    db.expire(a)
    assert db.get(Asset, a.id).content_state == AssetContentState.deleted


# ── 5. execute_manual da requested ──────────────────────────────────

def test_execute_manual_from_requested_raises(notif):
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=1)

    with pytest.raises(ValueError, match="approved"):
        execute_manual(db, req, user_id=2)
    assert req.status == "requested"


# ── 6. enqueue_verify ───────────────────────────────────────────────

def test_enqueue_verify_registered_asset(notif):
    db = _session()
    a = _asset(db, registered=True)
    req, _ = _approved_request(db, asset=a)

    job = enqueue_verify(db, req, user_id=2)

    assert isinstance(job, AgentJob)
    assert job.type == AgentJobType.delete_verify
    assert job.payload == {
        "volume_id": a.storage_volume_id,
        "rel_path": a.rel_path,
        "request_id": req.id,
    }
    assert req.agent_job_id == job.id
    assert req.executed_method == "agent_verify"
    assert req.status == "approved"  # resta approved fino al verify


def test_enqueue_verify_unregistered_asset_raises(notif):
    db = _session()
    req, _ = _approved_request(db)  # asset senza volume/rel_path
    with pytest.raises(ValueError, match="registrat"):
        enqueue_verify(db, req, user_id=2)


def test_enqueue_verify_from_requested_raises(notif):
    db = _session()
    a = _asset(db, registered=True)
    req = request_destruction(db, asset=a, reason="r", user_id=1)
    with pytest.raises(ValueError, match="approved"):
        enqueue_verify(db, req, user_id=2)


# ── 7. apply_verify_result / apply_verify_failure ───────────────────

def _verify_setup(db):
    a = _asset(db, registered=True)
    req, _ = _approved_request(db, asset=a)
    enqueue_verify(db, req, user_id=2)
    job = db.get(AgentJob, req.agent_job_id)
    return req, a, job


def test_apply_verify_result_exists_false_finalizes(notif):
    db = _session()
    req, a, job = _verify_setup(db)

    out = apply_verify_result(db, job, {"exists": False, "request_id": req.id})

    assert out.id == req.id
    assert req.status == "done"
    assert req.executed_method == "agent_verify"
    db.expire(a)
    assert db.get(Asset, a.id).content_state == AssetContentState.deleted
    mvs = db.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == a.id,
            AssetMovement.movement_type == AssetMovementType.destroyed)
    ).scalars().all()
    assert len(mvs) == 1


def test_apply_verify_result_exists_true_stays_approved(notif):
    db = _session()
    req, a, job = _verify_setup(db)

    apply_verify_result(db, job, {"exists": True, "request_id": req.id})

    assert req.status == "approved"
    db.expire(a)
    assert db.get(Asset, a.id).content_state == AssetContentState.online
    # notifica "ancora presente" al richiedente (user 1)
    assert any(1 in c["user_ids"] and "ancora presente" in c["title"]
               for c in notif.notify_calls)


def test_apply_verify_result_orphan_job_raises(notif):
    db = _session()
    req, a, job = _verify_setup(db)
    orphan = AgentJob(tenant_id=1, type=AgentJobType.delete_verify, payload={})
    db.add(orphan)
    db.flush()
    with pytest.raises(ValueError, match="[Nn]essuna"):
        apply_verify_result(db, orphan, {"exists": False})


def test_apply_verify_result_terminal_raises(notif):
    db = _session()
    req, a, job = _verify_setup(db)
    apply_verify_result(db, job, {"exists": False})
    with pytest.raises(ValueError, match="chiusa"):
        apply_verify_result(db, job, {"exists": False})


def test_apply_verify_failure_notifies_stays_approved(notif):
    db = _session()
    req, a, job = _verify_setup(db)

    apply_verify_failure(db, job, "volume_id 9 sconosciuto all'agent")

    assert req.status == "approved"
    assert any(1 in c["user_ids"] and "fallita" in c["title"].lower()
               for c in notif.notify_calls)


# ── 8. cancelled + terminali immutabili ─────────────────────────────

def test_cancel_from_requested_and_approved(notif):
    for setup_approved in (False, True):
        db = _session()
        a = _asset(db)
        req = request_destruction(db, asset=a, reason="r", user_id=1)
        if setup_approved:
            approve(db, req, user_id=2)

        transition(db, req, "cancelled", user_id=1)

        assert req.status == "cancelled"
        assert req.closed_at is not None
        assert req.closed_by_user_id == 1


def test_terminal_states_immutable(notif):
    # done
    db = _session()
    req, _ = _approved_request(db)
    execute_manual(db, req, user_id=2)
    for bad in ("requested", "approved", "cancelled", "done"):
        with pytest.raises(ValueError):
            transition(db, req, bad, user_id=1)
    with pytest.raises(ValueError):
        approve(db, req, user_id=9)
    with pytest.raises(ValueError):
        reject(db, req, user_id=9)
    with pytest.raises(ValueError):
        execute_manual(db, req, user_id=9)

    # rejected
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=1)
    reject(db, req, user_id=2)
    with pytest.raises(ValueError):
        transition(db, req, "cancelled", user_id=1)

    # cancelled
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=1)
    transition(db, req, "cancelled", user_id=1)
    with pytest.raises(ValueError):
        approve(db, req, user_id=2)


def test_transition_only_cancelled_externally(notif):
    """transition() accetta solo 'cancelled': gli altri stati hanno funzioni dedicate."""
    db = _session()
    a = _asset(db)
    req = request_destruction(db, asset=a, reason="r", user_id=1)
    with pytest.raises(ValueError, match="dedicat"):
        transition(db, req, "approved", user_id=2)


# ── agent: handle_job delete_verify ─────────────────────────────────

def test_agent_delete_verify_capability():
    from agent.main import CAPABILITIES
    assert "delete_verify" in CAPABILITIES


def test_agent_delete_verify_file_exists(tmp_path):
    from agent.main import handle_job
    vol_root = tmp_path / "san"
    vol_root.mkdir()
    (vol_root / "a.mxf").write_bytes(b"FAKE")

    status, result, error = handle_job(
        {"id": 1, "type": "delete_verify",
         "payload": {"volume_id": 1, "rel_path": "a.mxf", "request_id": 42}},
        {1: {"id": 1, "mount_path": str(vol_root)}}, {},
    )
    assert status == "done"
    assert error is None
    assert result == {"exists": True, "request_id": 42}


def test_agent_delete_verify_file_absent(tmp_path):
    from agent.main import handle_job
    vol_root = tmp_path / "san"
    vol_root.mkdir()

    status, result, error = handle_job(
        {"id": 2, "type": "delete_verify",
         "payload": {"volume_id": 1, "rel_path": "gone.mxf", "request_id": 43}},
        {1: {"id": 1, "mount_path": str(vol_root)}}, {},
    )
    assert status == "done"
    assert result == {"exists": False, "request_id": 43}


def test_agent_delete_verify_traversal_failed(tmp_path):
    from agent.main import handle_job
    vol_root = tmp_path / "san"
    vol_root.mkdir()

    status, result, error = handle_job(
        {"id": 3, "type": "delete_verify",
         "payload": {"volume_id": 1, "rel_path": "../../etc/passwd",
                     "request_id": 44}},
        {1: {"id": 1, "mount_path": str(vol_root)}}, {},
    )
    assert status == "failed"
    assert result is None
    assert "fuori dal volume" in (error or "")


def test_agent_delete_verify_unknown_volume():
    from agent.main import handle_job
    status, result, error = handle_job(
        {"id": 4, "type": "delete_verify",
         "payload": {"volume_id": 99, "rel_path": "a.mxf"}},
        {}, {},
    )
    assert status == "failed"
    assert "sconosciuto" in (error or "")


# ── wiring: POST /agent-api/jobs/{id}/result ────────────────────────

@pytest.fixture
def client_admin(monkeypatch):
    """Client admin con DB in-memory (pattern da test_f5_agent_transfer.py)."""
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    from app.services.auth import create_access_token
    from fastapi.testclient import TestClient
    from app.models import User, Role, Tenant
    from app.models.models import UserRole

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    session = TestSession()
    session.add(Tenant(id=1, name="T", slug="t1", is_active=True))
    session.flush()
    role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["edit_planning_all", "approve_destruction"],
        is_system=True, is_active=True,
    )
    session.add(role)
    session.flush()
    session.add(User(
        tenant_id=1, email="admin@test.local", full_name="Admin",
        hashed_password="x", role=UserRole.admin, role_id=role.id,
        is_active=True,
    ))
    session.commit()

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    token = create_access_token({"sub": "admin@test.local", "tid": 1})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def _setup_verify_job(session):
    """Volume + asset registrato + AgentNode + DestructionRequest approved
    + AgentJob delete_verify claimed."""
    from app.models.models import AgentNode, AgentJobStatus
    from app.services.agent_queue import generate_agent_token

    vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(vol)
    session.flush()

    asset = Asset(
        tenant_id=1, filename="master.mxf", original_name="master.mxf",
        file_path="OUT/master.mxf", file_size=1000,
        mime_type="application/mxf", asset_type=AssetType.video,
        uploaded_by=1, storage_volume_id=vol.id, rel_path="OUT/master.mxf",
    )
    session.add(asset)
    session.flush()

    plain, h = generate_agent_token()
    ag = AgentNode(tenant_id=1, name="agent-f6-test", auth_token_hash=h,
                   is_active=True)
    session.add(ag)
    session.flush()

    req = request_destruction(session, asset=asset, reason="fine retention",
                              user_id=1)
    approve(session, req, user_id=2)
    job = enqueue_verify(session, req, user_id=2)
    job.agent_id = ag.id
    job.status = AgentJobStatus.claimed
    session.commit()
    return plain, job, asset, req


def test_wiring_result_done_exists_false_finalizes(client_admin):
    session = client_admin.session
    plain, job, asset, req = _setup_verify_job(session)

    r = client_admin.post(
        f"/agent-api/jobs/{job.id}/result",
        json={"status": "done",
              "result": {"exists": False, "request_id": req.id}},
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text

    session.expire_all()
    req2 = session.get(DestructionRequest, req.id)
    assert req2.status == "done"
    assert session.get(Asset, asset.id).content_state == AssetContentState.deleted
    mvs = session.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == asset.id,
            AssetMovement.movement_type == AssetMovementType.destroyed)
    ).scalars().all()
    assert len(mvs) == 1
    assert mvs[0].contents_description == "fine retention"


def test_wiring_result_done_exists_true_stays_approved(client_admin):
    session = client_admin.session
    plain, job, asset, req = _setup_verify_job(session)

    r = client_admin.post(
        f"/agent-api/jobs/{job.id}/result",
        json={"status": "done",
              "result": {"exists": True, "request_id": req.id}},
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text

    session.expire_all()
    req2 = session.get(DestructionRequest, req.id)
    assert req2.status == "approved"
    assert session.get(Asset, asset.id).content_state == AssetContentState.online


def test_wiring_result_failed_stays_approved(client_admin):
    session = client_admin.session
    plain, job, asset, req = _setup_verify_job(session)

    r = client_admin.post(
        f"/agent-api/jobs/{job.id}/result",
        json={"status": "failed", "error": "volume non montato"},
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text

    session.expire_all()
    req2 = session.get(DestructionRequest, req.id)
    assert req2.status == "approved"
    # nessun movimento destroyed
    mvs = session.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == asset.id,
            AssetMovement.movement_type == AssetMovementType.destroyed)
    ).scalars().all()
    assert mvs == []
