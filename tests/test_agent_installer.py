"""tests/test_agent_installer.py — TDD Task 1: installer ZIP self-service.

Verifica endpoint GET /storage/api/agents/{agent_id}/installer:
1. 401/403 senza auth (redirect o 4xx — dipende dal middleware auth_guard)
2. 404 agent inesistente
3. 200: content-type zip, ZIP contiene i file attesi
4. claqo-agent.json contiene server_url non vuoto e token non vuoto
5. il token è valido: hash_agent_token(token) == agent.auth_token_hash ricaricato
6. avvia-agent.command ha external_attr eseguibile (0o755)
"""
import io
import zipfile
import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base
from app.models import User, Role, Tenant
from app.models.models import UserRole, AgentNode
from app.services.auth import create_access_token
from app.services.agent_queue import hash_agent_token


# ── Fixture: TestClient autenticato admin su DB in-memory isolato ────

@pytest.fixture
def client_admin(monkeypatch):
    """TestClient autenticato come admin su DB in-memory StaticPool.

    Pattern identico a test_naming_settings.py: monkeypatch dell'engine/SessionLocal
    di app.database + cookie access_token. Espone client.session per seeding.
    """
    import app.database as database
    import app.main as main_mod
    from app.database import get_db

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

    tenant = Tenant(id=1, name="Tenant Test", slug="tenant-test", is_active=True)
    session.add(tenant)
    session.flush()

    # admin_role con edit_planning_all (=RequireStorage)
    admin_role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["edit_planning_all", "manage_roles"],
        is_system=True, is_active=True,
    )
    session.add(admin_role)
    session.flush()

    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin Test",
        hashed_password="x", role=UserRole.admin, role_id=admin_role.id,
        is_active=True,
    )
    session.add(admin)
    session.commit()

    def _override_get_db():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    token = create_access_token({"sub": admin.email, "tid": 1})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def _make_agent(session, name="test-agent") -> AgentNode:
    """Crea un AgentNode attivo con token fittizio nel DB."""
    a = AgentNode(
        tenant_id=1,
        name=name,
        auth_token_hash="d" * 64,
        is_active=True,
    )
    session.add(a)
    session.commit()
    return a


# ── Test 1: 401/403 senza autenticazione ────────────────────────────

def test_unauthenticated_cannot_download(monkeypatch):
    """Senza cookie auth → 401 (current_user) o redirect 3xx."""
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    from sqlalchemy.pool import StaticPool

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
    tenant = Tenant(id=1, name="T", slug="t1", is_active=True)
    session.add(tenant)
    session.commit()

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    try:
        with TestClient(main_mod.app, follow_redirects=False) as c:
            r = c.get("/storage/api/agents/999/installer")
            assert r.status_code in (401, 403, 302, 307), \
                f"Atteso 401/403/redirect, ottenuto {r.status_code}"
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


# ── Test 2: 404 agent inesistente ───────────────────────────────────

def test_installer_404_unknown_agent(client_admin):
    r = client_admin.get("/storage/api/agents/99999/installer")
    assert r.status_code == 404


# ── Test 3: 200 + content-type + file attesi nel ZIP ────────────────

def test_installer_200_zip_structure(client_admin):
    agent = _make_agent(client_admin.session)
    r = client_admin.get(f"/storage/api/agents/{agent.id}/installer")
    assert r.status_code == 200, r.text
    assert "application/zip" in r.headers.get("content-type", "")
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "claqo-agent" in r.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()

    assert "claqo-agent/claqo-agent.json" in names, f"json mancante in {names}"
    assert "claqo-agent/agent/main.py" in names, f"main.py mancante in {names}"
    assert "claqo-agent/avvia-agent.command" in names, f".command mancante in {names}"
    assert "claqo-agent/avvia-agent.bat" in names, f".bat mancante in {names}"
    assert "claqo-agent/LEGGIMI.txt" in names, f"LEGGIMI.txt mancante in {names}"


# ── Test 4: claqo-agent.json ha server_url e token non vuoti ────────

def test_installer_json_fields_present(client_admin):
    import json
    agent = _make_agent(client_admin.session, name="ag-json-test")
    r = client_admin.get(f"/storage/api/agents/{agent.id}/installer")
    assert r.status_code == 200

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    cfg = json.loads(zf.read("claqo-agent/claqo-agent.json"))

    assert cfg.get("server_url"), "server_url è vuoto o mancante"
    assert cfg.get("token"), "token è vuoto o mancante"


# ── Test 5: il token nel json è valido e persistito ─────────────────

def test_installer_token_persisted_and_valid(client_admin):
    """Il download rigenera il token: hash nel DB deve corrispondere al plain nel JSON."""
    import json
    agent = _make_agent(client_admin.session, name="ag-token-test")
    old_hash = agent.auth_token_hash

    r = client_admin.get(f"/storage/api/agents/{agent.id}/installer")
    assert r.status_code == 200

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    cfg = json.loads(zf.read("claqo-agent/claqo-agent.json"))
    plain = cfg["token"]

    # Ricarica l'agent dal DB per vedere il nuovo hash
    client_admin.session.expire(agent)
    refreshed = client_admin.session.get(AgentNode, agent.id)

    # Il hash deve essere cambiato (token rigenerato)
    assert refreshed.auth_token_hash != old_hash, "auth_token_hash non è stato rigenerato"
    # Il plain deve corrispondere al nuovo hash
    assert hash_agent_token(plain) == refreshed.auth_token_hash, \
        "hash_agent_token(plain) != auth_token_hash in DB"


# ── Test 6: avvia-agent.command ha external_attr eseguibile ─────────

def test_installer_command_executable_attr(client_admin):
    """avvia-agent.command deve avere external_attr = 0o755 << 16."""
    agent = _make_agent(client_admin.session, name="ag-exec-test")
    r = client_admin.get(f"/storage/api/agents/{agent.id}/installer")
    assert r.status_code == 200

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    info = zf.getinfo("claqo-agent/avvia-agent.command")
    # external_attr: high 16 bit = Unix mode
    unix_mode = (info.external_attr >> 16) & 0o777
    assert unix_mode == 0o755, \
        f"Unix mode atteso 0o755, ottenuto 0o{unix_mode:o}"
