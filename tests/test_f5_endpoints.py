"""F5 (spec 2026-06-12) — Test integrazione endpoint TransferOrder.

Copertura (Task 4 del piano):
  1. GET  /storage/api/transfer-tools → [{key,label,mode}×2]
  2. POST /storage/api/transfers tool=manual → 200 + id
  3. POST /storage/api/transfers tool=aspera (asset registrato) → 200 + AgentJob
  4. POST /storage/api/transfers ValueError → 400 (tool ignoto, CSV vuoto)
  5. GET  /storage/api/transfers → lista serializzata + filtri tool/status
  6. POST /storage/api/transfers/{id}/close ok+link+scadenza → done + 2 movimenti outgest
  7. POST /storage/api/transfers/{id}/transition cancelled → 200
  8. Cross-tenant → 404 su close/transition
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base,
    AgentJob, AgentJobType,
    Asset, AssetType,
    AssetMovement, AssetMovementType,
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
                     "assign_resources"],
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

    # Volume SAN + asset registrato (volume + rel_path, per aspera)
    vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(vol)
    session.flush()

    asset_reg = Asset(
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
    session.add(asset_reg)

    asset_reg2 = Asset(
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
    session.add(asset_reg2)

    # Asset NON registrato (senza volume/rel_path — upload manuale)
    asset_plain = Asset(
        tenant_id=1,
        filename="doc.pdf",
        original_name="doc.pdf",
        file_path="uploads/doc.pdf",
        file_size=1_000,
        mime_type="application/pdf",
        asset_type=AssetType.document,
        uploaded_by=admin.id,
    )
    session.add(asset_plain)
    session.flush()
    session.commit()

    session._test_admin_id = admin.id
    session._test_vol_id = vol.id
    session._test_asset_reg_id = asset_reg.id
    session._test_asset_reg2_id = asset_reg2.id
    session._test_asset_plain_id = asset_plain.id

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


def _create_manual(client, *, destination="Share NAS partner", recipient="dest@example.com"):
    """Helper: crea un ordine manual con i 2 asset registrati."""
    session = client.session
    csv = f"{session._test_asset_reg_id},{session._test_asset_reg2_id}"
    r = client.post(
        "/storage/api/transfers",
        data={
            "tool": "manual",
            "asset_ids": csv,
            "destination": destination,
            "recipient_email": recipient,
            "note": "Nota test",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── Test 1: GET /storage/api/transfer-tools ──────────────────────────────────

def test_transfer_tools_list(client_admin):
    resp = client_admin.get("/storage/api/transfer-tools")
    assert resp.status_code == 200
    items = resp.json()
    by_key = {i["key"]: i for i in items}
    assert "manual" in by_key
    assert "aspera" in by_key
    assert by_key["manual"]["mode"] == "manual"
    assert by_key["aspera"]["mode"] == "agent"
    for i in items:
        assert set(i.keys()) == {"key", "label", "mode"}
        assert i["label"]


# ── Test 2: POST /storage/api/transfers (manual) ─────────────────────────────

def test_create_transfer_manual_ok(client_admin):
    order_id = _create_manual(client_admin)
    assert isinstance(order_id, int)

    session = client_admin.session
    order = session.get(TransferOrder, order_id)
    assert order is not None
    assert order.tool == "manual"
    assert order.status == "requested"
    assert order.agent_job_id is None
    assert order.requested_by_user_id == session._test_admin_id


def test_create_transfer_csv_tolerant(client_admin):
    """CSV con spazi e virgole spurie viene parsato in modo tollerante."""
    session = client_admin.session
    csv = f" {session._test_asset_reg_id} , , {session._test_asset_reg2_id} ,"
    r = client_admin.post(
        "/storage/api/transfers",
        data={"tool": "manual", "asset_ids": csv, "destination": "Share X"},
    )
    assert r.status_code == 200, r.text
    order = session.get(TransferOrder, r.json()["id"])
    assert set(order.asset_ids) == {
        session._test_asset_reg_id, session._test_asset_reg2_id,
    }


# ── Test 3: POST /storage/api/transfers (aspera → AgentJob) ──────────────────

def test_create_transfer_aspera_enqueues_job(client_admin):
    session = client_admin.session
    csv = f"{session._test_asset_reg_id},{session._test_asset_reg2_id}"
    r = client_admin.post(
        "/storage/api/transfers",
        data={"tool": "aspera", "asset_ids": csv,
              "destination": "user@host:/incoming"},
    )
    assert r.status_code == 200, r.text
    order = session.get(TransferOrder, r.json()["id"])
    assert order.agent_job_id is not None

    job = session.get(AgentJob, order.agent_job_id)
    assert job is not None
    assert job.type == AgentJobType.transfer
    assert job.payload["tool"] == "aspera"
    assert len(job.payload["files"]) == 2


# ── Test 4: ValueError → 400 ─────────────────────────────────────────────────

def test_create_transfer_unknown_tool_400(client_admin):
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/transfers",
        data={"tool": "fancytool",
              "asset_ids": str(session._test_asset_reg_id),
              "destination": "Share X"},
    )
    assert r.status_code == 400


def test_create_transfer_empty_csv_400(client_admin):
    r = client_admin.post(
        "/storage/api/transfers",
        data={"tool": "manual", "asset_ids": " , ,", "destination": "Share X"},
    )
    assert r.status_code == 400


def test_create_transfer_aspera_unregistered_asset_400(client_admin):
    """Asset senza volume/rel_path su tool agent-driven → 400 dal service."""
    session = client_admin.session
    r = client_admin.post(
        "/storage/api/transfers",
        data={"tool": "aspera",
              "asset_ids": str(session._test_asset_plain_id),
              "destination": "user@host:/incoming"},
    )
    assert r.status_code == 400


# ── Test 5: GET /storage/api/transfers + filtri ──────────────────────────────

def test_list_transfers_empty(client_admin):
    resp = client_admin.get("/storage/api/transfers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_transfers_serializer_and_filters(client_admin):
    session = client_admin.session
    _create_manual(client_admin)
    csv = str(session._test_asset_reg_id)
    r = client_admin.post(
        "/storage/api/transfers",
        data={"tool": "aspera", "asset_ids": csv,
              "destination": "user@host:/incoming"},
    )
    assert r.status_code == 200

    # Lista completa: 2 ordini, shape serializer
    resp = client_admin.get("/storage/api/transfers")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2
    for it in items:
        for field in ("id", "tool", "status", "destination", "recipient_email",
                      "note", "assets", "link_url", "link_expires_at",
                      "verification", "requested_by", "created_at", "closed_at"):
            assert field in it, f"campo mancante: {field}"
    manual = next(i for i in items if i["tool"] == "manual")
    assert len(manual["assets"]) == 2
    assert manual["assets"][0]["filename"] == "feature_2k.mxf"
    assert manual["assets"][0]["id"] == session._test_asset_reg_id
    assert manual["requested_by"] == "Admin User"
    assert manual["status"] == "requested"

    # Filtro tool
    resp2 = client_admin.get("/storage/api/transfers?tool=aspera")
    items2 = resp2.json()
    assert len(items2) == 1
    assert items2[0]["tool"] == "aspera"

    # Filtro status
    resp3 = client_admin.get("/storage/api/transfers?status=done")
    assert resp3.json() == []
    resp4 = client_admin.get("/storage/api/transfers?status=requested")
    assert len(resp4.json()) == 2


# ── Test 6: POST /{id}/close con link + scadenza → done + movimenti ──────────

def test_close_transfer_ok_with_link(client_admin):
    session = client_admin.session
    order_id = _create_manual(client_admin)

    resp = client_admin.post(
        f"/storage/api/transfers/{order_id}/close",
        data={
            "ok": "true",
            "method": "manual",
            "details": "Verificato a mano",
            "link_url": "https://share.example.com/dl/abc",
            "link_expires_at": "2026-12-31",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "done"

    order = session.get(TransferOrder, order_id)
    assert order.status == "done"
    assert order.link_url == "https://share.example.com/dl/abc"
    assert order.link_expires_at is not None
    assert order.link_expires_at.year == 2026
    assert order.link_expires_at.month == 12
    assert order.link_expires_at.day == 31
    assert order.link_expires_at.hour == 23  # fine giornata
    assert order.verification["method"] == "manual"
    assert order.verification["ok"] is True
    assert order.closed_by_user_id == session._test_admin_id

    # 2 AssetMovement outgest creati
    movs = session.execute(
        select(AssetMovement).where(
            AssetMovement.contents_description == f"TransferOrder #{order_id}")
    ).scalars().all()
    assert len(movs) == 2
    for mv in movs:
        assert mv.movement_type == AssetMovementType.outgest
        assert mv.carrier == "manual"
        assert mv.to_contact == "dest@example.com"

    # Il serializer espone link + scadenza in lista
    items = client_admin.get("/storage/api/transfers?status=done").json()
    assert len(items) == 1
    assert items[0]["link_url"] == "https://share.example.com/dl/abc"
    assert items[0]["link_expires_at"] is not None


def test_close_transfer_already_closed_400(client_admin):
    order_id = _create_manual(client_admin)
    r1 = client_admin.post(
        f"/storage/api/transfers/{order_id}/close",
        data={"ok": "true", "method": "manual"},
    )
    assert r1.status_code == 200
    r2 = client_admin.post(
        f"/storage/api/transfers/{order_id}/close",
        data={"ok": "true", "method": "manual"},
    )
    assert r2.status_code == 400


def test_close_transfer_bad_date_400(client_admin):
    order_id = _create_manual(client_admin)
    r = client_admin.post(
        f"/storage/api/transfers/{order_id}/close",
        data={"ok": "true", "method": "manual",
              "link_expires_at": "31/12/2026"},
    )
    assert r.status_code == 400


# ── Test 7: POST /{id}/transition cancelled ──────────────────────────────────

def test_transition_transfer_cancelled(client_admin):
    session = client_admin.session
    order_id = _create_manual(client_admin)

    resp = client_admin.post(
        f"/storage/api/transfers/{order_id}/transition",
        data={"status": "cancelled"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "status": "cancelled"}
    assert session.get(TransferOrder, order_id).status == "cancelled"

    # Transizione da terminale → 400
    r2 = client_admin.post(
        f"/storage/api/transfers/{order_id}/transition",
        data={"status": "in_progress"},
    )
    assert r2.status_code == 400


# ── Test 8: Cross-tenant → 404 ──────────────────────────────────────────────

def test_cross_tenant_transfer_404(client_admin):
    session = client_admin.session
    order_t2 = TransferOrder(
        tenant_id=2, tool="manual", destination="altrove",
        asset_ids=[1], status="requested",
    )
    session.add(order_t2)
    session.commit()

    r1 = client_admin.post(
        f"/storage/api/transfers/{order_t2.id}/transition",
        data={"status": "cancelled"},
    )
    assert r1.status_code == 404

    r2 = client_admin.post(
        f"/storage/api/transfers/{order_t2.id}/close",
        data={"ok": "true", "method": "manual"},
    )
    assert r2.status_code == 404
