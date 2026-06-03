"""Endpoint GET/PUT /settings/api/naming-conventions (NC-T3).

Naming convention di default del tenant (video/audio): GET lazy (ritorna i
default industry con is_default=True se non salvate), PUT persiste e normalizza.
Tenant-scoped + admin-gated come fs-scan-paths.

Il fixture `client_admin` è replicato da tests/test_billable_hours_mode.py:
TestClient autenticato come admin su un DB SQLite in-memory isolato (StaticPool),
con app.database.engine/SessionLocal puntati allo stesso engine così che il
middleware auth_guard e l'endpoint vedano lo stesso DB. Adattamento NC-T3: il
seed include un Tenant(id=1) — l'endpoint fa query Tenant by id e ritorna 404 se
assente (test_billable_hours_mode non ne aveva bisogno).
"""
import json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_admin(monkeypatch):
    """TestClient autenticato come admin su un DB in-memory isolato.

    Aggancia `app.database.engine`+`SessionLocal` allo stesso engine in-memory
    usato dall'override di `get_db`, così che il middleware `auth_guard`
    (che apre la sua SessionLocal) e l'endpoint vedano lo stesso DB.
    Espone `c.session` per costruire dati nel test.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.models import Base
    from app.models import User, Role, Tenant
    from app.models.models import UserRole
    import app.database as database
    import app.main as main_mod
    from app.services.auth import create_access_token

    # StaticPool: una sola connessione condivisa → il middleware (che apre la
    # propria SessionLocal su un'altra connessione) vede le stesse tabelle del
    # DB :memory:. Senza StaticPool ogni connessione SQLite in-memory è un DB
    # vuoto distinto → "no such table: users".
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # Il middleware apre la sua SessionLocal → puntala allo stesso engine.
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)

    session = TestSession()

    # Seed: tenant default (NC-T3: l'endpoint fa query Tenant by id) +
    # ruolo admin (manage_roles → is_admin True) + utente attivo.
    tenant = Tenant(id=1, name="Tenant Test", slug="tenant-test", is_active=True)
    session.add(tenant)
    session.flush()
    admin_role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["manage_roles"], is_system=True, is_active=True,
    )
    session.add(admin_role)
    session.flush()
    # NB: l'endpoint naming-conventions usa `_require_admin` che controlla la
    # colonna enum legacy `User.role`, non il Role FK (manage_roles). Settiamo
    # quindi anche `role=UserRole.admin` (oltre al role_id, per coerenza).
    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin Test",
        hashed_password="x", role=UserRole.admin, role_id=admin_role.id,
        is_active=True,
    )
    session.add(admin)
    session.commit()

    from app.database import get_db

    def _override_get_db():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    token = create_access_token({"sub": admin.email, "tid": 1})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"}) as c:
            c.session = session  # comodo per i fixture dati
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def test_get_returns_defaults_when_unset(client_admin):
    r = client_admin.get("/settings/api/naming-conventions")
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True
    assert "video" in body["conventions"] and "audio" in body["conventions"]
    assert body["conventions"]["video"]["pattern"]


def test_put_persists_and_get_reflects(client_admin):
    payload = {
        "video": {"pattern": "{project_code}_{project_title}", "tokens": ["project_code", "project_title"], "case": "upper"},
        "audio": {"pattern": "{project_code}_{audio_config}", "tokens": ["project_code", "audio_config"]},
    }
    r = client_admin.put("/settings/api/naming-conventions", data={"conventions_json": json.dumps(payload)})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    g = client_admin.get("/settings/api/naming-conventions")
    body = g.json()
    assert body["is_default"] is False
    assert body["conventions"]["video"]["pattern"] == "{project_code}_{project_title}"
    assert body["conventions"]["video"]["case"] == "upper"


def test_token_help_exposed(client_admin):
    r = client_admin.get("/settings/api/naming-conventions")
    assert isinstance(r.json().get("token_help"), list)
    assert any(t["token"] == "project_code" for t in r.json()["token_help"])
