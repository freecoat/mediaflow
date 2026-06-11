"""F3 (spec 2026-06-11) — PUT /agent-api/jobs/{job_id}/preview-upload.

Test: scrittura atomica del proxy preview, cap, auth checks, job type check.
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


# ── fixture client_admin (copia esatta da test_storage_browse.py) ────────────

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
    role = Role(tenant_id=1, code="admin", name="Admin",
                permissions=["edit_planning_all"], is_system=True, is_active=True)
    session.add(role)
    session.flush()
    session.add(User(tenant_id=1, email="admin@test.local", full_name="Admin",
                     hashed_password="x", role=UserRole.admin, role_id=role.id,
                     is_active=True))
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


# ── test 1: scrittura file + update campi Asset ───────────────────────────────

def test_upload_writes_file_and_sets_path(client_admin, tmp_path, monkeypatch):
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    plain, ag, job, a = _setup(client_admin.session)

    content = b"FAKEMP4" * 100
    r = client_admin.put(
        f"/agent-api/jobs/{job.id}/preview-upload",
        content=content,
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["bytes"] == len(content)

    dest = tmp_path / "1" / f"{a.id}.mp4"
    assert dest.is_file()
    assert dest.read_bytes() == content

    # Rilegge da DB per verificare i campi Asset
    client_admin.session.expire_all()
    a2 = client_admin.session.get(Asset, a.id)
    assert a2.preview_path == str(dest)
    assert a2.preview_storage == "local"


# ── test 2: token agent sbagliato → 404 ──────────────────────────────────────

def test_upload_wrong_agent_404(client_admin, tmp_path, monkeypatch):
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    plain, ag, job, a = _setup(client_admin.session)

    # Secondo AgentNode con altro token
    plain2, h2 = generate_agent_token()
    ag2 = AgentNode(
        tenant_id=1,
        name="agent-other",
        auth_token_hash=h2,
        is_active=True,
    )
    client_admin.session.add(ag2)
    client_admin.session.commit()

    r = client_admin.put(
        f"/agent-api/jobs/{job.id}/preview-upload",
        content=b"data",
        headers={"X-Agent-Token": plain2},
    )
    assert r.status_code == 404


# ── test 3: job type sbagliato → 404 ─────────────────────────────────────────

def test_upload_wrong_job_type_404(client_admin, tmp_path, monkeypatch):
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    plain, ag, job, a = _setup(client_admin.session)

    # Job type=probe claimato dallo stesso agent
    probe_job = enqueue_job(
        client_admin.session,
        tenant_id=1,
        type=AgentJobType.probe,
        payload={"volume_id": 1, "rel_path": "OUT/e.mxf"},
    )
    probe_job.agent_id = ag.id
    probe_job.status = AgentJobStatus.claimed
    client_admin.session.commit()

    r = client_admin.put(
        f"/agent-api/jobs/{probe_job.id}/preview-upload",
        content=b"data",
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 404


# ── test 4: cap 413 + nessun file .part residuo ───────────────────────────────

def test_upload_cap_413(client_admin, tmp_path, monkeypatch):
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)
    monkeypatch.setenv("PREVIEW_MAX_GB", "0")

    plain, ag, job, a = _setup(client_admin.session)

    r = client_admin.put(
        f"/agent-api/jobs/{job.id}/preview-upload",
        content=b"X" * 1024,
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 413

    # Nessun file .part deve restare su disco
    parts = list(tmp_path.rglob("*.part"))
    assert parts == [], f"file .part residui: {parts}"


# ── test 5: job non claimato → 404 ───────────────────────────────────────────

def test_upload_unclaimed_job_404(client_admin, tmp_path, monkeypatch):
    import app.services.asset_preview as ap_mod
    monkeypatch.setattr(ap_mod, "PREVIEW_DIR", tmp_path)

    plain, ag, job_orig, a = _setup(client_admin.session)

    # Crea un job preview con status=queued e agent_id=None
    unclaimed_job = enqueue_job(
        client_admin.session,
        tenant_id=1,
        type=AgentJobType.preview,
        payload={
            "asset_id": a.id,
            "volume_id": 1,
            "rel_path": "OUT/e.mxf",
            "upload": {"mode": "server"},
        },
    )
    # status=queued, agent_id=None (default da enqueue_job)
    client_admin.session.commit()

    r = client_admin.put(
        f"/agent-api/jobs/{unclaimed_job.id}/preview-upload",
        content=b"data",
        headers={"X-Agent-Token": plain},
    )
    assert r.status_code == 404
