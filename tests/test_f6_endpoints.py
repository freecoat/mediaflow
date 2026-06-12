"""F6 (spec 2026-06-12) — Test integrazione endpoint distruzione,
asset-map e storage-report.

Copertura (Task 4 del piano):
  1. POST /storage/api/destructions → 200 / reason vuota 400 / asset 404 /
     cross-tenant 404 / doppia richiesta attiva 400
  2. GET  /storage/api/destructions?status= → serializer batch + filtro
  3. POST /{id}/approve → gate RBAC ok ma self-approval 400; con richiedente
     diverso → 200
  4. POST /{id}/reject, /execute-manual, /enqueue-verify → flussi + errori 400
  5. POST /{id}/transition cancelled → 200; terminale → 400; cross-tenant 404
  6. GET  /storage/api/asset-map → shape + filtri + solo confirmed + pending
  7. GET  /storage/api/storage-report → chiavi + conteggi coerenti col seed
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base,
    Asset, AssetType,
    AssetContentState, AssetProposedState,
    AssetMembership, AssetMovement, AssetMovementType,
    Client,
    DestructionRequest,
    Job, JobDeliverable,
    PhysicalAsset, PhysicalAssetKind, AssetOwnerType,
    Project,
    StorageVolume,
    Tenant,
    TransferOrder,
    User, UserRole,
)
from app.models import Role


# ── Fixture client_admin (pattern tests/test_f4_endpoints.py) ─────────────────

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

    # Tenant 1 (default)
    session.add(Tenant(id=1, name="TestCo", slug="testco", is_active=True))
    session.flush()

    role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["edit_planning_all", "edit_deliverables",
                     "assign_resources", "approve_destruction"],
        is_system=True, is_active=True,
    )
    session.add(role)
    session.flush()

    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin User",
        hashed_password="x", role=UserRole.admin, role_id=role.id,
        is_active=True,
    )
    session.add(admin)
    session.flush()

    # Secondo utente (richiedente fittizio per testare l'approve 200)
    other = User(
        tenant_id=1, email="other@test.local", full_name="Other User",
        hashed_password="x", role=UserRole.staff, role_id=role.id,
        is_active=True,
    )
    session.add(other)
    session.flush()

    # Client + Project + Job (per JobDeliverable)
    cli = Client(tenant_id=1, name="ClienteTest")
    session.add(cli)
    session.flush()
    proj = Project(tenant_id=1, code="PROJ001", title="Progetto Test",
                   client_id=cli.id)
    session.add(proj)
    session.flush()
    job = Job(tenant_id=1, code="JOB001", title="Job Test",
              project_id=proj.id, client_id=cli.id)
    session.add(job)
    session.flush()

    # Volume SAN
    vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san",
                        total_gb=1000.0, free_gb=400.0)
    session.add(vol)
    session.flush()

    # Asset 1: confermato, registrato, con tape membership + deliverable link
    asset1 = Asset(
        tenant_id=1,
        filename="feature_2k.mxf",
        original_name="feature_2k.mxf",
        file_path="OUT/feature_2k.mxf",
        file_size=1_000_000_000,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=admin.id,
        storage_volume_id=vol.id,
        rel_path="OUT/feature_2k.mxf",
    )
    session.add(asset1)
    session.flush()

    # Asset 2: confermato, registrato, senza tape/deliverable
    asset2 = Asset(
        tenant_id=1,
        filename="audio_51.wav",
        original_name="audio_51.wav",
        file_path="OUT/audio_51.wav",
        file_size=500_000_000,
        mime_type="audio/wav",
        asset_type=AssetType.audio,
        uploaded_by=admin.id,
        storage_volume_id=vol.id,
        rel_path="OUT/audio_51.wav",
    )
    session.add(asset2)
    session.flush()

    # Asset 3: pending_review (NON deve apparire in asset-map)
    asset_pending = Asset(
        tenant_id=1,
        filename="pending.mov",
        original_name="pending.mov",
        file_path="IN/pending.mov",
        file_size=10_000,
        mime_type="video/quicktime",
        asset_type=AssetType.video,
        uploaded_by=admin.id,
        storage_volume_id=vol.id,
        rel_path="IN/pending.mov",
        proposed_state=AssetProposedState.pending_review,
    )
    session.add(asset_pending)
    session.flush()

    # Tape LTO + membership attiva su asset1
    tape = PhysicalAsset(
        tenant_id=1,
        project_id=proj.id,
        kind=PhysicalAssetKind.lto,
        label="LTO #001 - Test",
        owner_type=AssetOwnerType.internal,
        is_internal_archive=True,
        logistics_status="in_storage",
        qr_code_token="testtoken001",
    )
    session.add(tape)
    session.flush()
    session.add(AssetMembership(
        tenant_id=1, physical_asset_id=tape.id, asset_id=asset1.id,
        file_size=asset1.file_size,
    ))
    # Membership orfana (asset_id None) per orphan_memberships
    session.add(AssetMembership(
        tenant_id=1, physical_asset_id=tape.id, asset_id=None,
        path_on_media="/ORPHANS/x.mxf", file_size=123,
    ))
    session.flush()

    # Deliverable linkato (digital_asset_id reverse) su asset1
    deliv = JobDeliverable(
        tenant_id=1, job_id=job.id, name="DCP 2K Feature",
        digital_asset_id=asset1.id,
    )
    session.add(deliv)
    session.flush()

    # TransferOrder done che include asset1 → transfer_count=1
    session.add(TransferOrder(
        tenant_id=1, tool="manual", destination="Share X",
        asset_ids=[asset1.id], status="done",
    ))
    # TransferOrder requested (NON conta come done, conta in pending)
    session.add(TransferOrder(
        tenant_id=1, tool="manual", destination="Share Y",
        asset_ids=[asset1.id, asset2.id], status="requested",
    ))
    session.commit()

    session._test_admin_id = admin.id
    session._test_other_id = other.id
    session._test_vol_id = vol.id
    session._test_asset1_id = asset1.id
    session._test_asset2_id = asset2.id
    session._test_asset_pending_id = asset_pending.id
    session._test_tape_id = tape.id
    session._test_deliv_id = deliv.id

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    token = create_access_token({"sub": "admin@test.local", "tid": 1})
    try:
        with TestClient(main_mod.app,
                        headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def _request_via_service(session, asset_id, *, user_id, reason="Reason TPN"):
    """Crea una DestructionRequest via service con richiedente arbitrario."""
    from app.services.destruction import request_destruction
    asset = session.get(Asset, asset_id)
    req = request_destruction(session, asset=asset, reason=reason,
                              user_id=user_id, tenant_id=1)
    session.commit()
    return req


# ── Test 1: POST /storage/api/destructions ────────────────────────────────────

def test_create_destruction_ok(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "Fine progetto"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    req = session.get(DestructionRequest, body["id"])
    assert req.status == "requested"
    assert req.reason == "Fine progetto"
    assert req.requested_by_user_id == session._test_admin_id


def test_create_destruction_empty_reason_400(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "   "},
    )
    assert r.status_code == 400


def test_create_destruction_asset_not_found_404(client_admin):
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": 99999, "reason": "x"},
    )
    assert r.status_code == 404


def test_create_destruction_cross_tenant_404(client_admin):
    session = client_admin.session
    a_t2 = Asset(
        tenant_id=2, filename="t2.mxf", original_name="t2.mxf",
        file_path="x/t2.mxf", file_size=1, mime_type="application/mxf",
        asset_type=AssetType.video, uploaded_by=session._test_admin_id,
    )
    session.add(a_t2)
    session.commit()
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": a_t2.id, "reason": "x"},
    )
    assert r.status_code == 404


def test_create_destruction_duplicate_active_400(client_admin):
    session = client_admin.session
    r1 = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "prima"},
    )
    assert r1.status_code == 200
    r2 = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "seconda"},
    )
    assert r2.status_code == 400


# ── Test 2: GET /storage/api/destructions ─────────────────────────────────────

def test_list_destructions_serializer_and_filter(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset1_id, "reason": "Audit list"},
    )
    assert r.status_code == 200

    resp = client_admin.get("/storage/api/destructions")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    it = items[0]
    for field in ("id", "status", "reason", "executed_method", "asset",
                  "requested_by", "approved_by", "created_at", "closed_at"):
        assert field in it, f"campo mancante: {field}"
    assert it["status"] == "requested"
    assert it["asset"]["id"] == session._test_asset1_id
    assert it["asset"]["filename"] == "feature_2k.mxf"
    assert it["requested_by"] == "Admin User"
    assert it["approved_by"] is None
    assert it["executed_method"] is None
    assert it["created_at"] is not None
    assert it["closed_at"] is None

    # Filtro status
    assert client_admin.get("/storage/api/destructions?status=requested").json()
    assert client_admin.get("/storage/api/destructions?status=done").json() == []


# ── Test 3: POST /{id}/approve ────────────────────────────────────────────────

def test_approve_self_approval_400(client_admin):
    """Il richiedente (admin) NON può approvare la propria richiesta,
    anche se ha il permesso approve_destruction → 400 dal service."""
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "self"},
    )
    rid = r.json()["id"]
    resp = client_admin.post(f"/storage/api/destructions/{rid}/approve")
    assert resp.status_code == 400


def test_approve_ok_with_other_requester(client_admin):
    """Richiesta creata via service da un altro utente → admin approva 200."""
    session = client_admin.session
    req = _request_via_service(session, session._test_asset2_id,
                               user_id=session._test_other_id)
    resp = client_admin.post(f"/storage/api/destructions/{req.id}/approve")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    session.refresh(req)
    assert req.status == "approved"
    assert req.approved_by_user_id == session._test_admin_id


def test_approve_not_found_404(client_admin):
    resp = client_admin.post("/storage/api/destructions/99999/approve")
    assert resp.status_code == 404


def test_approve_cross_tenant_404(client_admin):
    session = client_admin.session
    req_t2 = DestructionRequest(tenant_id=2, asset_id=1, reason="t2")
    session.add(req_t2)
    session.commit()
    resp = client_admin.post(f"/storage/api/destructions/{req_t2.id}/approve")
    assert resp.status_code == 404


# ── Test 4: reject / execute-manual / enqueue-verify ─────────────────────────

def test_reject_ok(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "da rifiutare"},
    )
    rid = r.json()["id"]
    resp = client_admin.post(f"/storage/api/destructions/{rid}/reject")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rejected"
    req = session.get(DestructionRequest, rid)
    assert req.status == "rejected"
    assert req.closed_at is not None


def test_reject_from_approved_400(client_admin):
    session = client_admin.session
    req = _request_via_service(session, session._test_asset2_id,
                               user_id=session._test_other_id)
    assert client_admin.post(
        f"/storage/api/destructions/{req.id}/approve").status_code == 200
    resp = client_admin.post(f"/storage/api/destructions/{req.id}/reject")
    assert resp.status_code == 400


def test_execute_manual_ok_deleted(client_admin):
    """Asset SENZA membership tape → content_state=deleted + movimento."""
    session = client_admin.session
    req = _request_via_service(session, session._test_asset2_id,
                               user_id=session._test_other_id,
                               reason="distruzione manuale")
    assert client_admin.post(
        f"/storage/api/destructions/{req.id}/approve").status_code == 200
    resp = client_admin.post(f"/storage/api/destructions/{req.id}/execute-manual")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "done"

    session.refresh(req)
    assert req.status == "done"
    assert req.executed_method == "manual"
    asset = session.get(Asset, session._test_asset2_id)
    assert asset.content_state == AssetContentState.deleted
    movs = session.execute(
        select(AssetMovement).where(
            AssetMovement.asset_id == session._test_asset2_id,
            AssetMovement.movement_type == AssetMovementType.destroyed,
        )
    ).scalars().all()
    assert len(movs) == 1
    assert movs[0].contents_description == "distruzione manuale"


def test_execute_manual_archived_only_with_tape(client_admin):
    """Asset CON membership tape attiva → content_state=archived_only."""
    session = client_admin.session
    req = _request_via_service(session, session._test_asset1_id,
                               user_id=session._test_other_id)
    assert client_admin.post(
        f"/storage/api/destructions/{req.id}/approve").status_code == 200
    resp = client_admin.post(f"/storage/api/destructions/{req.id}/execute-manual")
    assert resp.status_code == 200, resp.text
    asset = session.get(Asset, session._test_asset1_id)
    assert asset.content_state == AssetContentState.archived_only


def test_execute_manual_from_requested_400(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "x"},
    )
    rid = r.json()["id"]
    resp = client_admin.post(f"/storage/api/destructions/{rid}/execute-manual")
    assert resp.status_code == 400


def test_enqueue_verify_ok(client_admin):
    session = client_admin.session
    req = _request_via_service(session, session._test_asset2_id,
                               user_id=session._test_other_id)
    assert client_admin.post(
        f"/storage/api/destructions/{req.id}/approve").status_code == 200
    resp = client_admin.post(f"/storage/api/destructions/{req.id}/enqueue-verify")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["job_id"], int)
    session.refresh(req)
    assert req.executed_method == "agent_verify"
    assert req.agent_job_id == body["job_id"]


def test_enqueue_verify_unregistered_asset_400(client_admin):
    """Asset senza volume/rel_path → ValueError dal service → 400."""
    session = client_admin.session
    plain = Asset(
        tenant_id=1, filename="doc.pdf", original_name="doc.pdf",
        file_path="uploads/doc.pdf", file_size=1_000,
        mime_type="application/pdf", asset_type=AssetType.document,
        uploaded_by=session._test_admin_id,
    )
    session.add(plain)
    session.commit()
    req = _request_via_service(session, plain.id,
                               user_id=session._test_other_id)
    assert client_admin.post(
        f"/storage/api/destructions/{req.id}/approve").status_code == 200
    resp = client_admin.post(f"/storage/api/destructions/{req.id}/enqueue-verify")
    assert resp.status_code == 400


# ── Test 5: POST /{id}/transition ─────────────────────────────────────────────

def test_transition_cancelled_ok(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset2_id, "reason": "annulla"},
    )
    rid = r.json()["id"]
    resp = client_admin.post(
        f"/storage/api/destructions/{rid}/transition",
        data={"status": "cancelled"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "status": "cancelled"}

    # Da terminale → 400
    r2 = client_admin.post(
        f"/storage/api/destructions/{rid}/transition",
        data={"status": "cancelled"},
    )
    assert r2.status_code == 400


def test_transition_cancelled_by_admin_not_requester(client_admin):
    """Richiesta di altro utente: l'admin (has approve_destruction →
    is_admin=True) può annullarla comunque."""
    session = client_admin.session
    req = _request_via_service(session, session._test_asset2_id,
                               user_id=session._test_other_id)
    resp = client_admin.post(
        f"/storage/api/destructions/{req.id}/transition",
        data={"status": "cancelled"},
    )
    assert resp.status_code == 200, resp.text


def test_transition_cross_tenant_404(client_admin):
    session = client_admin.session
    req_t2 = DestructionRequest(tenant_id=2, asset_id=1, reason="t2")
    session.add(req_t2)
    session.commit()
    resp = client_admin.post(
        f"/storage/api/destructions/{req_t2.id}/transition",
        data={"status": "cancelled"},
    )
    assert resp.status_code == 404


# ── Test 6: GET /storage/api/asset-map ────────────────────────────────────────

def test_asset_map_shape_and_batch(client_admin):
    session = client_admin.session
    resp = client_admin.get("/storage/api/asset-map")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["truncated"] is False
    items = body["items"]
    # SOLO confirmed: asset_pending escluso
    ids = {i["id"] for i in items}
    assert session._test_asset1_id in ids
    assert session._test_asset2_id in ids
    assert session._test_asset_pending_id not in ids

    by_id = {i["id"]: i for i in items}
    a1 = by_id[session._test_asset1_id]
    for field in ("id", "filename", "content_state", "volume", "tapes",
                  "preview_status", "transfer_count", "deliverable",
                  "destruction_pending"):
        assert field in a1, f"campo mancante: {field}"
    assert a1["filename"] == "feature_2k.mxf"
    assert a1["content_state"] == "online"
    assert a1["volume"] == {"id": session._test_vol_id, "name": "SAN"}
    assert a1["tapes"] == [{"id": session._test_tape_id,
                            "label": "LTO #001 - Test"}]
    assert a1["preview_status"] == "none"
    assert a1["transfer_count"] == 1  # solo l'ordine done conta
    assert a1["deliverable"] == {"id": session._test_deliv_id,
                                 "name": "DCP 2K Feature"}
    assert a1["destruction_pending"] is False

    a2 = by_id[session._test_asset2_id]
    assert a2["tapes"] == []
    assert a2["transfer_count"] == 0
    assert a2["deliverable"] is None


def test_asset_map_destruction_pending(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset1_id, "reason": "pending badge"},
    )
    assert r.status_code == 200
    items = client_admin.get("/storage/api/asset-map").json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[session._test_asset1_id]["destruction_pending"] is True
    assert by_id[session._test_asset2_id]["destruction_pending"] is False


def test_asset_map_filters(client_admin):
    session = client_admin.session

    # Filtro q su filename
    items = client_admin.get("/storage/api/asset-map?q=feature").json()["items"]
    assert [i["id"] for i in items] == [session._test_asset1_id]

    # Filtro volume_id
    items = client_admin.get(
        f"/storage/api/asset-map?volume_id={session._test_vol_id}"
    ).json()["items"]
    assert {i["id"] for i in items} == {session._test_asset1_id,
                                        session._test_asset2_id}
    items = client_admin.get("/storage/api/asset-map?volume_id=999").json()["items"]
    assert items == []

    # Filtro content_state
    asset2 = session.get(Asset, session._test_asset2_id)
    asset2.content_state = AssetContentState.deleted
    session.commit()
    items = client_admin.get(
        "/storage/api/asset-map?content_state=deleted").json()["items"]
    assert [i["id"] for i in items] == [session._test_asset2_id]
    items = client_admin.get(
        "/storage/api/asset-map?content_state=online").json()["items"]
    assert {i["id"] for i in items} == {session._test_asset1_id}


def test_asset_map_tenant_scope(client_admin):
    session = client_admin.session
    a_t2 = Asset(
        tenant_id=2, filename="t2.mxf", original_name="t2.mxf",
        file_path="x/t2.mxf", file_size=1, mime_type="application/mxf",
        asset_type=AssetType.video, uploaded_by=session._test_admin_id,
    )
    session.add(a_t2)
    session.commit()
    items = client_admin.get("/storage/api/asset-map").json()["items"]
    assert a_t2.id not in {i["id"] for i in items}


# ── Test 7: GET /storage/api/storage-report ──────────────────────────────────

def test_storage_report_keys_and_counts(client_admin):
    session = client_admin.session
    resp = client_admin.get("/storage/api/storage-report")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("volumes", "tapes", "content_states", "orphan_memberships",
                "previews", "pending"):
        assert key in body, f"chiave mancante: {key}"

    # volumes: SAN con 2 asset confermati registrati (pending escluso? no:
    # il report conta il registry confermato)
    vols = {v["name"]: v for v in body["volumes"]}
    assert "SAN" in vols
    san = vols["SAN"]
    assert san["asset_count"] == 2
    assert san["bytes_total"] == 1_500_000_000
    assert san["total_gb"] == 1000.0
    assert san["free_gb"] == 400.0

    # tapes: LTO #001 con 1 file matchato + 1 orfano = 2 membership attive
    tapes = {t["label"]: t for t in body["tapes"]}
    assert "LTO #001 - Test" in tapes
    assert tapes["LTO #001 - Test"]["file_count"] == 2

    # content_states: 2 online (confermati)
    assert body["content_states"].get("online") == 2

    # orphan_memberships: 1
    assert body["orphan_memberships"] == 1

    # previews: nessuna ready
    assert body["previews"] == {"count": 0, "bytes_total": 0}

    # pending: 1 proposta + 1 transfer requested + 0 ticket + 0 distruzioni
    pend = body["pending"]
    assert pend["proposals"] == 1
    assert pend["tickets_open"] == 0
    assert pend["transfers_open"] == 1
    assert pend["destructions_open"] == 0


def test_storage_report_destructions_open_counts(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/destructions",
        data={"asset_id": session._test_asset1_id, "reason": "report count"},
    )
    assert r.status_code == 200
    body = client_admin.get("/storage/api/storage-report").json()
    assert body["pending"]["destructions_open"] == 1
