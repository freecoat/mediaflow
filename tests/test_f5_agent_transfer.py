"""F5 (spec 2026-06-12) — Test agent/transfer.py + wiring server process_job_result.

Test puri (1-5): nessun DB, nessun server.
Test wiring (6): endpoint POST /agent-api/jobs/{id}/result con job transfer
                 → ordine TransferOrder passa a "done" e crea AssetMovement outgest.
"""
from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# 1. build_ascp_cmd con key_path + extra_args
# ─────────────────────────────────────────────────────────────────────────────

def test_build_ascp_cmd_with_key_and_extra():
    from agent.transfer import build_ascp_cmd

    cmd = build_ascp_cmd(
        ["/mnt/a.mxf", "/mnt/b.wav"],
        "user@host:/in",
        key_path="/k/id_rsa",
        extra_args=["-l", "500M"],
    )
    assert cmd == [
        "ascp", "-i", "/k/id_rsa",
        "-l", "500M",
        "-d",
        "/mnt/a.mxf", "/mnt/b.wav",
        "user@host:/in",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 2. build_ascp_cmd senza key_path → niente "-i"
# ─────────────────────────────────────────────────────────────────────────────

def test_build_ascp_cmd_without_key():
    from agent.transfer import build_ascp_cmd

    cmd = build_ascp_cmd(["/mnt/a.mxf"], "user@host:/in")
    assert "-i" not in cmd
    assert cmd[0] == "ascp"
    assert cmd[-1] == "user@host:/in"
    assert "/mnt/a.mxf" in cmd
    assert "-d" in cmd


# ─────────────────────────────────────────────────────────────────────────────
# 3. run_transfer con ascp assente → RuntimeError messaggio chiaro
# ─────────────────────────────────────────────────────────────────────────────

def test_run_transfer_ascp_missing(monkeypatch):
    from agent import transfer as tr_mod

    monkeypatch.setattr(tr_mod.shutil, "which", lambda _: None)

    with pytest.raises(RuntimeError, match="ascp non trovato"):
        tr_mod.run_transfer(
            {"files": [{"volume_id": 1, "rel_path": "a.mxf"}],
             "destination": "user@host:/in"},
            {1: {"mount_path": "/mnt/san"}},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. traversal bloccato: rel_path "../../etc" → ValueError "fuori dal volume"
# ─────────────────────────────────────────────────────────────────────────────

def test_run_transfer_traversal_blocked(monkeypatch, tmp_path):
    from agent import transfer as tr_mod
    import shutil as shutil_mod

    # ascp finto presente
    monkeypatch.setattr(tr_mod.shutil, "which", lambda _: "/usr/bin/ascp")

    vol_root = tmp_path / "san"
    vol_root.mkdir()

    with pytest.raises(ValueError, match="fuori dal volume"):
        tr_mod.run_transfer(
            {"files": [{"volume_id": 1, "rel_path": "../../etc/passwd"}],
             "destination": "user@host:/in"},
            {1: {"mount_path": str(vol_root)}},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 5a. run_transfer con subprocess mockato rc=0 → {ok:True, files:2, log_tail str}
# 5b. rc=1 → RuntimeError con stderr tail
# ─────────────────────────────────────────────────────────────────────────────

def test_run_transfer_subprocess_ok(monkeypatch, tmp_path):
    from agent import transfer as tr_mod
    import subprocess

    # Crea file reali nella root del volume
    vol_root = tmp_path / "san"
    vol_root.mkdir()
    f1 = vol_root / "a.mxf"
    f2 = vol_root / "b.wav"
    f1.write_bytes(b"FAKE1")
    f2.write_bytes(b"FAKE2")

    monkeypatch.setattr(tr_mod.shutil, "which", lambda _: "/usr/bin/ascp")

    # Mock subprocess.run → rc 0
    class FakeProc:
        returncode = 0
        stdout = "Session started\nTransfer complete\n"
        stderr = ""

    monkeypatch.setattr(tr_mod.subprocess, "run", lambda *a, **kw: FakeProc())

    result = tr_mod.run_transfer(
        {
            "files": [
                {"volume_id": 1, "rel_path": "a.mxf"},
                {"volume_id": 1, "rel_path": "b.wav"},
            ],
            "destination": "user@host:/in",
        },
        {1: {"mount_path": str(vol_root)}},
    )
    assert result["ok"] is True
    assert result["files"] == 2
    assert isinstance(result["log_tail"], str)


def test_run_transfer_subprocess_failure(monkeypatch, tmp_path):
    from agent import transfer as tr_mod

    vol_root = tmp_path / "san"
    vol_root.mkdir()
    f1 = vol_root / "a.mxf"
    f1.write_bytes(b"FAKE")

    monkeypatch.setattr(tr_mod.shutil, "which", lambda _: "/usr/bin/ascp")

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "Session Error: authentication failed"

    monkeypatch.setattr(tr_mod.subprocess, "run", lambda *a, **kw: FakeProc())

    with pytest.raises(RuntimeError, match="ascp rc=1"):
        tr_mod.run_transfer(
            {"files": [{"volume_id": 1, "rel_path": "a.mxf"}],
             "destination": "user@host:/in"},
            {1: {"mount_path": str(vol_root)}},
        )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Wiring server: POST /agent-api/jobs/{id}/result done su job transfer
#    → TransferOrder passa a "done" + 1 AssetMovement outgest creato
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client_admin(monkeypatch):
    """Client admin con DB in-memory (pattern da test_f3_preview_endpoints.py)."""
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    from app.services.auth import create_access_token
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from fastapi.testclient import TestClient
    from app.models.models import Base
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
        permissions=["edit_planning_all", "assign_resources", "view_finance"],
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


def _setup_transfer_job(session):
    """Crea: Volume, Asset registrato, AgentNode, TransferOrder, AgentJob transfer claimed."""
    from app.models.models import (
        StorageVolume, Asset, AssetType, AgentNode, AgentJobType,
        AgentJobStatus, TransferOrder,
    )
    from app.services.agent_queue import generate_agent_token, enqueue_job

    vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(vol)
    session.flush()

    asset = Asset(
        tenant_id=1,
        filename="master.mxf",
        original_name="master.mxf",
        file_path="OUT/master.mxf",
        file_size=1000,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol.id,
        rel_path="OUT/master.mxf",
    )
    session.add(asset)
    session.flush()

    plain, h = generate_agent_token()
    ag = AgentNode(
        tenant_id=1,
        name="agent-transfer-test",
        auth_token_hash=h,
        is_active=True,
    )
    session.add(ag)
    session.flush()

    # Crea ordine aspera
    order = TransferOrder(
        tenant_id=1,
        tool="aspera",
        destination="user@host:/deliver",
        recipient_email="client@example.com",
        asset_ids=[asset.id],
        status="requested",
        requested_by_user_id=1,
    )
    session.add(order)
    session.flush()

    # Accoda job transfer
    job = enqueue_job(
        session,
        tenant_id=1,
        type=AgentJobType.transfer,
        payload={
            "tool": "aspera",
            "files": [{"volume_id": vol.id, "rel_path": "OUT/master.mxf"}],
            "destination": "user@host:/deliver",
            "extra_args": [],
        },
        asset_id=asset.id,
    )
    # Linka ordine → job
    order.agent_job_id = job.id
    # Simula claim
    job.agent_id = ag.id
    job.status = AgentJobStatus.claimed
    session.commit()

    return plain, ag, job, asset, order


def test_wiring_result_done_closes_transfer_order(client_admin):
    """POST /agent-api/jobs/{id}/result done su job transfer
    → TransferOrder.status == 'done' e 1 AssetMovement outgest."""
    from app.models.models import TransferOrder, AssetMovement, AssetMovementType
    from sqlalchemy import select

    session = client_admin.session
    plain, ag, job, asset, order = _setup_transfer_job(session)

    r = client_admin.post(
        f"/agent-api/jobs/{job.id}/result",
        json={
            "status": "done",
            "result": {
                "ok": True,
                "files": 1,
                "log_tail": "Session started\nTransfer complete",
            },
        },
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text

    session.expire_all()

    # Ordine chiuso correttamente
    order2 = session.get(TransferOrder, order.id)
    assert order2.status == "done", f"atteso done, ottenuto {order2.status!r}"
    assert order2.verification is not None
    assert order2.verification["method"] == "tool_rc"
    assert order2.verification["ok"] is True

    # AssetMovement outgest creato
    mvs = session.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == asset.id,
            AssetMovement.movement_type == AssetMovementType.outgest,
        )
    ).scalars().all()
    assert len(mvs) == 1, f"atteso 1 movimento, trovati {len(mvs)}"
    mv = mvs[0]
    assert mv.to_party == "user@host:/deliver"
    assert mv.carrier == "aspera"
    assert "TransferOrder" in (mv.contents_description or "")
