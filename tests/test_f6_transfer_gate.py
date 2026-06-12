"""F6 Task 3 — TPN gate transfer whitelist.

Casi TDD:
  1. transfer_allowed OPEN → True sempre (con/senza whitelist)
  2. transfer_allowed LOCKDOWN + whitelist match substring case-insensitive → True
  3. transfer_allowed LOCKDOWN + whitelist no match → False
  4. transfer_allowed LOCKDOWN + whitelist vuota → False
  5. transfer_allowed LOCKDOWN + whitelist None → False
  6. transfer_allowed tenant None → False (fail-closed)
  7. assert_transfer_allowed solleva EgressLocked(vector="transfer")
  8. create_order in LOCKDOWN senza match → EgressLocked
  9. create_order in LOCKDOWN con match → ordine creato correttamente
 10. endpoint POST /storage/api/transfers in LOCKDOWN senza match → 403
 11. endpoint POST /storage/api/transfers in OPEN → 200
 12. round-trip whitelist dal pannello Sicurezza (GET→POST→GET)
"""
import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base,
    Asset, AssetType,
    Tenant,
    TransferOrder,
    User, UserRole,
)
from app.models import Role
from app.services import egress_guard
from app.services.egress_guard import (
    OPEN, LOCKDOWN,
    EgressLocked,
    transfer_allowed,
    assert_transfer_allowed,
)


# ── helpers ─────────────────────────────────────────────────────────────────

def _tenant_ns(master=OPEN, whitelist=None, tid=1):
    """SimpleNamespace duck-typed come Tenant per test puri senza DB."""
    return SimpleNamespace(
        id=tid,
        lockdown_master=master,
        transfer_destination_whitelist=whitelist,
    )


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


# ── 1. OPEN → True sempre ────────────────────────────────────────────────────

def test_transfer_allowed_open_no_whitelist():
    t = _tenant_ns(OPEN, whitelist=None)
    assert transfer_allowed(t, "user@evil.com:/data") is True


def test_transfer_allowed_open_with_whitelist():
    """OPEN ignora la whitelist → sempre True."""
    t = _tenant_ns(OPEN, whitelist=["aspera.netflix.com"])
    assert transfer_allowed(t, "user@evil.com:/data") is True


def test_transfer_allowed_open_empty_destination():
    t = _tenant_ns(OPEN, whitelist=None)
    assert transfer_allowed(t, "") is True


# ── 2. LOCKDOWN + match → True ───────────────────────────────────────────────

def test_transfer_allowed_lockdown_match_host_exact():
    t = _tenant_ns(LOCKDOWN, whitelist=["aspera.netflix.com", "warnerbros.com"])
    assert transfer_allowed(t, "user@aspera.netflix.com:/in") is True


def test_transfer_allowed_lockdown_match_subdomain_suffix():
    """Voce dominio → match anchored su sottodominio (host.endswith('.'+voce))."""
    t = _tenant_ns(LOCKDOWN, whitelist=["warnerbros.com"])
    assert transfer_allowed(t, "user@backlot.warnerbros.com:/delivery") is True


def test_transfer_allowed_lockdown_match_case_insensitive():
    t = _tenant_ns(LOCKDOWN, whitelist=["ASPERA.NETFLIX.COM"])
    assert transfer_allowed(t, "user@Aspera.Netflix.Com:/in") is True


# ── 2b. Bypass substring NON deve passare (anchored host match) ──────────────

def test_transfer_allowed_lockdown_no_substring_prefix_bypass():
    """`netflix.com` NON deve matchare `evil-netflix.com.attacker.com`."""
    t = _tenant_ns(LOCKDOWN, whitelist=["netflix.com"])
    assert transfer_allowed(t, "user@evil-netflix.com.attacker.com:/x") is False


def test_transfer_allowed_lockdown_no_suffix_domain_bypass():
    """`netflix.com` NON deve matchare `netflix.com.evil.com`."""
    t = _tenant_ns(LOCKDOWN, whitelist=["netflix.com"])
    assert transfer_allowed(t, "user@netflix.com.evil.com:/x") is False


def test_transfer_allowed_lockdown_manual_exact_match():
    """Destination libera (no host) → match ESATTO, non substring."""
    t = _tenant_ns(LOCKDOWN, whitelist=["Backlot S3 share"])
    assert transfer_allowed(t, "Backlot S3 share") is True
    assert transfer_allowed(t, "prefix Backlot S3 share suffix") is False


# ── 3. LOCKDOWN + no match → False ───────────────────────────────────────────

def test_transfer_allowed_lockdown_no_match():
    t = _tenant_ns(LOCKDOWN, whitelist=["aspera.netflix.com", "backlot"])
    assert transfer_allowed(t, "user@evil.com:/x") is False


# ── 4/5. LOCKDOWN + whitelist vuota/None → False ────────────────────────────

def test_transfer_allowed_lockdown_empty_whitelist():
    t = _tenant_ns(LOCKDOWN, whitelist=[])
    assert transfer_allowed(t, "user@anywhere.com:/path") is False


def test_transfer_allowed_lockdown_none_whitelist():
    t = _tenant_ns(LOCKDOWN, whitelist=None)
    assert transfer_allowed(t, "user@anywhere.com:/path") is False


# ── 6. tenant None → False (fail-closed) ────────────────────────────────────

def test_transfer_allowed_none_tenant():
    assert transfer_allowed(None, "user@anywhere.com:/path") is False


# ── 7. assert_transfer_allowed solleva EgressLocked(vector="transfer") ───────

def test_assert_transfer_allowed_raises_egress_locked():
    t = _tenant_ns(LOCKDOWN, whitelist=None, tid=7)
    with pytest.raises(EgressLocked) as ei:
        assert_transfer_allowed(t, "user@evil.com:/x")
    assert ei.value.vector == "transfer"
    assert ei.value.tenant_id == 7


def test_assert_transfer_allowed_passes_when_open():
    t = _tenant_ns(OPEN)
    assert_transfer_allowed(t, "user@anywhere.com:/path")  # no exception


def test_assert_transfer_allowed_passes_when_lockdown_match():
    t = _tenant_ns(LOCKDOWN, whitelist=["aspera.netflix.com"])
    assert_transfer_allowed(t, "user@aspera.netflix.com:/in")  # no exception


# ── 8. create_order in LOCKDOWN senza match → EgressLocked ──────────────────

def test_create_order_lockdown_no_match_raises():
    from app.services.transfer_orders import create_order

    db = _session()
    tenant = Tenant(id=1, name="TestCo", slug="testco",
                    lockdown_master=LOCKDOWN,
                    transfer_destination_whitelist=["aspera.netflix.com"],
                    is_active=True)
    db.add(tenant)
    a = Asset(
        tenant_id=1, filename="file.mxf", original_name="file.mxf",
        file_path="/san/file.mxf", mime_type="application/mxf",
        file_size=1_000_000, asset_type=AssetType.video, uploaded_by=1,
    )
    db.add(a)
    db.flush()

    with pytest.raises(EgressLocked) as ei:
        create_order(
            db,
            tool="manual",
            asset_ids=[a.id],
            destination="user@evil.com:/x",
            tenant_id=1,
        )
    assert ei.value.vector == "transfer"


# ── 9. create_order in LOCKDOWN con match → OK ──────────────────────────────

def test_create_order_lockdown_with_match_ok():
    from app.services.transfer_orders import create_order

    db = _session()
    tenant = Tenant(id=1, name="TestCo", slug="testco",
                    lockdown_master=LOCKDOWN,
                    transfer_destination_whitelist=["aspera.netflix.com"],
                    is_active=True)
    db.add(tenant)
    a = Asset(
        tenant_id=1, filename="file.mxf", original_name="file.mxf",
        file_path="/san/file.mxf", mime_type="application/mxf",
        file_size=1_000_000, asset_type=AssetType.video, uploaded_by=1,
    )
    db.add(a)
    db.flush()

    order = create_order(
        db,
        tool="manual",
        asset_ids=[a.id],
        destination="user@aspera.netflix.com:/in",
        tenant_id=1,
    )
    assert order.status == "requested"
    assert order.destination == "user@aspera.netflix.com:/in"


# ── 10/11. endpoint POST /storage/api/transfers 403/200 ─────────────────────

@pytest.fixture
def client_admin(monkeypatch):
    """Client TestClient con admin e Tenant OPEN (default).

    Segue il pattern di test_f5_endpoints: dependency_overrides per get_db +
    cookie inviato come header HTTP (non via client.cookies che non persiste).
    """
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

    tenant = Tenant(id=1, name="TestCo", slug="testco",
                    lockdown_master=OPEN,
                    transfer_destination_whitelist=None,
                    is_active=True)
    session.add(tenant)
    session.flush()

    role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["edit_planning_all", "edit_deliverables",
                     "assign_resources", "manage_cloud_lockdown"],
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

    asset = Asset(
        tenant_id=1, filename="test.mxf", original_name="test.mxf",
        file_path="/san/test.mxf", mime_type="application/mxf",
        file_size=500_000, asset_type=AssetType.video, uploaded_by=admin.id,
    )
    session.add(asset)
    session.flush()
    session.commit()

    token = create_access_token({"sub": "admin@test.local", "tid": 1})

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    try:
        with TestClient(
            main_mod.app,
            headers={"Cookie": f"access_token={token}"},
            follow_redirects=False,
            raise_server_exceptions=False,
        ) as c:
            c._asset_id = asset.id
            c._session = session
            c._engine = engine
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


def test_endpoint_transfer_open_200(client_admin):
    """In OPEN il transfer va a buon fine (200)."""
    r = client_admin.post(
        "/storage/api/transfers",
        data={
            "tool": "manual",
            "asset_ids": str(client_admin._asset_id),
            "destination": "user@evil.com:/x",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_endpoint_transfer_lockdown_no_match_403(client_admin):
    """In LOCKDOWN senza match → 403 via EgressLocked handler globale."""
    # Aggiorna il tenant nel DB e invalida la cache della sessione
    from sqlalchemy import text as sa_text
    client_admin._session.execute(
        sa_text(
            "UPDATE tenants SET lockdown_master='LOCKDOWN', "
            "transfer_destination_whitelist=:wl WHERE id=1"
        ),
        {"wl": json.dumps(["aspera.netflix.com"])},
    )
    client_admin._session.commit()
    client_admin._session.expire_all()

    r = client_admin.post(
        "/storage/api/transfers",
        data={
            "tool": "manual",
            "asset_ids": str(client_admin._asset_id),
            "destination": "user@evil.com:/x",
        },
    )
    assert r.status_code == 403, r.text


def test_endpoint_transfer_lockdown_with_match_200(client_admin):
    """In LOCKDOWN con match → 200."""
    from sqlalchemy import text as sa_text
    client_admin._session.execute(
        sa_text(
            "UPDATE tenants SET lockdown_master='LOCKDOWN', "
            "transfer_destination_whitelist=:wl WHERE id=1"
        ),
        {"wl": json.dumps(["aspera.netflix.com"])},
    )
    client_admin._session.commit()
    client_admin._session.expire_all()

    r = client_admin.post(
        "/storage/api/transfers",
        data={
            "tool": "manual",
            "asset_ids": str(client_admin._asset_id),
            "destination": "user@aspera.netflix.com:/in",
        },
    )
    assert r.status_code == 200, r.text


# ── 12. round-trip whitelist dal pannello Sicurezza ──────────────────────────

def test_lockdown_whitelist_roundtrip(client_admin):
    """POST /settings/api/lockdown con whitelist → GET restituisce la stessa lista."""
    whitelist_text = "aspera.netflix.com\nbacklot.warnerbros.com\n  \n"
    expected = ["aspera.netflix.com", "backlot.warnerbros.com"]

    # POST: salva lockdown con whitelist
    r_post = client_admin.post(
        "/settings/api/lockdown",
        data={
            "master": "LOCKDOWN",
            "cloud_ai_enabled": "true",
            "web_search_enabled": "true",
            "enrichment_enabled": "true",
            "reason": "test",
            "transfer_destination_whitelist": whitelist_text,
        },
    )
    assert r_post.status_code == 200, r_post.text
    body = r_post.json()
    assert body["ok"] is True
    assert body["transfer_destination_whitelist"] == expected

    # GET: verifica persistenza
    r_get = client_admin.get("/settings/api/lockdown")
    assert r_get.status_code == 200, r_get.text
    got = r_get.json()
    assert got["master"] == "LOCKDOWN"
    assert got["transfer_destination_whitelist"] == expected


def test_lockdown_whitelist_empty_roundtrip(client_admin):
    """Whitelist vuota → None salvato → GET ritorna []."""
    r_post = client_admin.post(
        "/settings/api/lockdown",
        data={
            "master": "LOCKDOWN",
            "cloud_ai_enabled": "true",
            "web_search_enabled": "true",
            "enrichment_enabled": "true",
            "reason": "",
            "transfer_destination_whitelist": "   \n  \n",
        },
    )
    assert r_post.status_code == 200, r_post.text
    assert r_post.json()["transfer_destination_whitelist"] == []

    r_get = client_admin.get("/settings/api/lockdown")
    assert r_get.json()["transfer_destination_whitelist"] == []
