"""F3 Task 6 — auto_preview per-volume + trigger alla conferma proposta.

Test:
  1. confirm su volume con auto_preview=True → accoda AgentJob type=preview
  2. confirm su volume con auto_preview=False → nessun job preview
  3. confirm su volume auto_preview=True ma asset senza rel_path → 200, 0 job (ValueError ingoiata)
  4. roundtrip form: POST volumes auto_preview="true" → list → True; PUT "false" → False
"""
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base, AgentJob, AgentJobType,
    Asset, AssetType, AssetProposedState, StorageVolume,
)
from app.models import User, Role, Tenant
from app.models.models import UserRole


# ── fixture client_admin ──────────────────────────────────────────────────────

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


# ── helper _proposal ──────────────────────────────────────────────────────────

def _proposal(session, auto: bool, *, with_relpath: bool = True):
    """Crea StorageVolume(auto_preview=auto) + Asset pending_review collegato."""
    vol = StorageVolume(tenant_id=1, name="SAN-ap", mount_path="/mnt/san",
                        auto_preview=auto)
    session.add(vol)
    session.flush()

    a = Asset(
        tenant_id=1,
        filename="master.mxf",
        original_name="master.mxf",
        file_path="projects/master.mxf",
        file_size=1,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=1,
        storage_volume_id=vol.id,
        rel_path="projects/master.mxf" if with_relpath else None,
        proposed_state=AssetProposedState.pending_review,
    )
    session.add(a)
    session.commit()
    return a


# ── test 1: confirm → job preview accodato (auto=True) ───────────────────────

def test_confirm_enqueues_preview_when_auto(client_admin, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _proposal(client_admin.session, auto=True)

    r = client_admin.post(f"/storage/api/proposals/{a.id}/confirm", data={})
    assert r.status_code == 200, r.text

    client_admin.session.expire_all()
    jobs = client_admin.session.query(AgentJob).filter(
        AgentJob.type == AgentJobType.preview
    ).all()
    assert len(jobs) == 1
    assert jobs[0].payload.get("asset_id") == a.id


# ── test 2: confirm → nessun job preview (auto=False) ────────────────────────

def test_confirm_no_preview_when_flag_off(client_admin, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _proposal(client_admin.session, auto=False)

    r = client_admin.post(f"/storage/api/proposals/{a.id}/confirm", data={})
    assert r.status_code == 200, r.text

    client_admin.session.expire_all()
    jobs = client_admin.session.query(AgentJob).filter(
        AgentJob.type == AgentJobType.preview
    ).all()
    assert len(jobs) == 0


# ── test 3: auto=True ma asset senza rel_path → 200, 0 job ───────────────────

def test_confirm_auto_preview_tollerante_su_asset_senza_relpath(client_admin, monkeypatch):
    monkeypatch.delenv("PREVIEW_S3_BUCKET", raising=False)
    a = _proposal(client_admin.session, auto=True, with_relpath=False)

    r = client_admin.post(f"/storage/api/proposals/{a.id}/confirm", data={})
    assert r.status_code == 200, r.text

    client_admin.session.expire_all()
    jobs = client_admin.session.query(AgentJob).filter(
        AgentJob.type == AgentJobType.preview
    ).all()
    assert len(jobs) == 0


# ── test 4: roundtrip form auto_preview ──────────────────────────────────────

def test_volume_form_roundtrip_auto_preview(client_admin):
    # Crea volume con auto_preview=true
    r = client_admin.post("/storage/api/volumes", data={
        "name": "RoundtripVol",
        "mount_path": "/mnt/rt",
        "auto_preview": "true",
    })
    assert r.status_code == 200, r.text
    vol_id = r.json()["id"]

    # Verifica list
    vols = client_admin.get("/storage/api/volumes").json()
    match = next((v for v in vols if v["id"] == vol_id), None)
    assert match is not None
    assert match["auto_preview"] is True

    # Aggiorna a false
    r2 = client_admin.put(f"/storage/api/volumes/{vol_id}", data={
        "name": "RoundtripVol",
        "mount_path": "/mnt/rt",
        "auto_preview": "false",
    })
    assert r2.status_code == 200, r2.text

    vols2 = client_admin.get("/storage/api/volumes").json()
    match2 = next((v for v in vols2 if v["id"] == vol_id), None)
    assert match2 is not None
    assert match2["auto_preview"] is False
