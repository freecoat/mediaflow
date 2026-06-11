"""F3 (spec 2026-06-11) — Preview endpoints in /qc + process_job_result wiring.

Tests:
1. test_result_done_marks_ready        — POST /agent-api/jobs/{id}/result done → asset ready
2. test_result_failed_marks_failed     — POST /agent-api/jobs/{id}/result failed → asset failed
3. test_player_serves_local_file_with_range — GET /qc/api/assets/{id}/preview local file + Range
4. test_player_404_when_not_ready      — GET /qc/api/assets/{id}/preview not ready → 404
5. test_status_and_generate            — POST generate → job_id; GET status → JSON
6. test_player_cross_tenant_404        — asset tenant 2 → 404
"""
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base, AgentJob, AgentJobType, AgentJobStatus,
    AgentNode, Asset, AssetType, StorageVolume,
)
from app.models import User, Role, Tenant
from app.models.models import UserRole
from app.services.agent_queue import generate_agent_token, enqueue_job


# ── fixture client_admin ───────────────────────────────────────────────────────
# Copia esatta da test_f3_preview_upload.py + "view_finance" e "assign_resources"
# nei permessi del ruolo admin (necessari per _check_read/_check_write in qc.py)

@pytest.fixture
def client_admin(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    from app.services.auth import create_access_token

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
        permissions=[
            "edit_planning_all",
            "assign_resources",
            "view_finance",
        ],
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


# ── helper condiviso ──────────────────────────────────────────────────────────

def _setup(session):
    """Crea: StorageVolume tenant 1; Asset con storage_volume_id+rel_path;
    AgentNode con token attivo; AgentJob type=preview status=claimed."""
    vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(vol)
    session.flush()

    a = Asset(
        tenant_id=1,
        filename="e.mxf",
        original_name="e.mxf",
        file_path="OUT/e.mxf",
        file_size=1,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol.id,
        rel_path="OUT/e.mxf",
    )
    session.add(a)
    session.flush()

    plain, h = generate_agent_token()
    ag = AgentNode(
        tenant_id=1,
        name="agent-test",
        auth_token_hash=h,
        is_active=True,
    )
    session.add(ag)
    session.flush()

    job = enqueue_job(
        session,
        tenant_id=1,
        type=AgentJobType.preview,
        payload={
            "asset_id": a.id,
            "volume_id": vol.id,
            "rel_path": "OUT/e.mxf",
            "upload": {"mode": "server"},
        },
    )
    # Simula claim: agent_id + status claimed
    job.agent_id = ag.id
    job.status = AgentJobStatus.claimed
    session.commit()

    return plain, ag, job, a


# ── test 1: result done → asset ready ─────────────────────────────────────────

def test_result_done_marks_ready(client_admin, tmp_path, monkeypatch):
    """POST /agent-api/jobs/{id}/result con status=done deve marcare asset ready."""
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    plain, ag, job, a = _setup(client_admin.session)

    # Scrivi il file preview in locale come farebbe il preview-upload step
    dest = tmp_path / "1" / f"{a.id}.mp4"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"FAKEMP4")

    r = client_admin.post(
        f"/agent-api/jobs/{job.id}/result",
        json={
            "status": "done",
            "result": {
                "uploaded": "server",
                "start_tc": "01:00:00:00",
                "fps": 25.0,
                "duration_sec": 3600.0,
                "burned_tc": True,
            },
        },
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text

    client_admin.session.expire_all()
    a2 = client_admin.session.get(Asset, a.id)
    assert a2.preview_status == "ready"
    assert a2.preview_meta is not None
    assert a2.preview_meta["fps"] == 25.0


# ── test 2: result failed → asset failed ──────────────────────────────────────

def test_result_failed_marks_failed(client_admin, tmp_path, monkeypatch):
    """POST /agent-api/jobs/{id}/result con status=failed deve marcare asset failed."""
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    plain, ag, job, a = _setup(client_admin.session)

    r = client_admin.post(
        f"/agent-api/jobs/{job.id}/result",
        json={
            "status": "failed",
            "error": "ffmpeg rc=1: encoder error",
        },
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text

    client_admin.session.expire_all()
    a2 = client_admin.session.get(Asset, a.id)
    assert a2.preview_status == "failed"
    assert a2.preview_error is not None
    assert "ffmpeg" in a2.preview_error


# ── test 3: player serve file locale + Range ──────────────────────────────────

def test_player_serves_local_file_with_range(client_admin, tmp_path, monkeypatch):
    """GET /qc/api/assets/{id}/preview → 200 con file; Range header → 206."""
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    _plain, _ag, _job, a = _setup(client_admin.session)

    # Prepara file preview e marcia asset ready
    dest = ap_mod.local_path_for(a)
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = b"0123456789"
    dest.write_bytes(content)

    a.preview_status = "ready"
    a.preview_storage = "local"
    a.preview_path = str(dest)
    client_admin.session.commit()

    # GET senza Range → 200
    r = client_admin.get(f"/qc/api/assets/{a.id}/preview")
    assert r.status_code == 200, r.text

    # GET con Range header bytes=2-5 → 206
    r2 = client_admin.get(
        f"/qc/api/assets/{a.id}/preview",
        headers={"Range": "bytes=2-5"},
    )
    assert r2.status_code == 206, r2.text
    assert r2.content == b"2345"


# ── test 4: player 404 quando asset non ready ─────────────────────────────────

def test_player_404_when_not_ready(client_admin, tmp_path, monkeypatch):
    """GET /qc/api/assets/{id}/preview → 404 se preview_status != 'ready'."""
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    _plain, _ag, _job, a = _setup(client_admin.session)

    # Asset non ha preview (default status="none")
    r = client_admin.get(f"/qc/api/assets/{a.id}/preview")
    assert r.status_code == 404, r.text


# ── test 5: status + generate ──────────────────────────────────────────────────

def test_status_and_generate(client_admin, tmp_path, monkeypatch):
    """POST generate → 200 con job_id (idempotente su job già in claimed);
    GET status → JSON con campo 'status'."""
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    _plain, _ag, job, a = _setup(client_admin.session)
    # Il job è già in claimed (da _setup) → enqueue_preview ritorna il job esistente (idempotente)

    r_gen = client_admin.post(f"/qc/api/assets/{a.id}/preview/generate")
    assert r_gen.status_code == 200, r_gen.text
    body = r_gen.json()
    assert "job_id" in body
    assert body["ok"] is True

    r_status = client_admin.get(f"/qc/api/assets/{a.id}/preview/status")
    assert r_status.status_code == 200, r_status.text
    status_body = r_status.json()
    assert "status" in status_body


# ── test 6: cross-tenant 404 ──────────────────────────────────────────────────

def test_player_cross_tenant_404(client_admin, tmp_path, monkeypatch):
    """GET /qc/api/assets/{id}/preview con asset tenant 2 → 404."""
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    # Crea tenant 2
    session = client_admin.session
    session.add(Tenant(id=2, name="T2", slug="t2", is_active=True))
    session.flush()

    vol2 = StorageVolume(tenant_id=2, name="SAN2", mount_path="/mnt/san2")
    session.add(vol2)
    session.flush()

    # Asset di tenant 2
    a2 = Asset(
        tenant_id=2,
        filename="other.mxf",
        original_name="other.mxf",
        file_path="OUT/other.mxf",
        file_size=1,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol2.id,
        rel_path="OUT/other.mxf",
        preview_status="ready",
        preview_storage="local",
        preview_path=str(tmp_path / "2" / "other.mp4"),
    )
    session.add(a2)
    session.commit()

    # L'utente admin@test.local è di tenant 1 → deve ricevere 404 per l'asset di tenant 2
    r = client_admin.get(f"/qc/api/assets/{a2.id}/preview")
    assert r.status_code == 404, r.text
