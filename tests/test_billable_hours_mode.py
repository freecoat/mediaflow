"""Policy ore fatturabili per-booking (v3.5.0-alpha.172.179).

`compute_billable_hours` è la single source of truth: la usa sia il cost report
(via _booking_billable_hours) sia l'endpoint preview. Le opzioni impattano SOLO
le ore-cliente; il costo interno (non testato qui) somma sempre tutti.
"""
from app.services import cost_line_sync as cls

HUM = "person_internal"
FRE = "person_freelance"
ROOM = "studio"


def test_single_human_default_max():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0


def test_two_humans_max():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0


def test_two_humans_sum():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "sum") == 14.0


def test_two_humans_specific():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "specific", specific_rid=2) == 6.0


def test_specific_resource_absent_returns_zero():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "specific", specific_rid=99) == 0.0


def test_manual_overrides_everything():
    items = [(1, HUM, 8.0), (2, HUM, 6.0)]
    assert cls.compute_billable_hours(items, "manual", manual=5.0) == 5.0


def test_manual_none_is_zero():
    items = [(1, HUM, 8.0)]
    assert cls.compute_billable_hours(items, "manual", manual=None) == 0.0


def test_human_plus_room_ignores_room():
    items = [(1, HUM, 8.0), (10, ROOM, 8.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0  # 1 sola umana


def test_smart_split_same_human_aggregated_before_max():
    items = [(1, HUM, 4.0), (1, HUM, 4.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0


def test_only_rooms_max_mode_ignored():
    items = [(10, ROOM, 8.0), (11, ROOM, 4.0)]
    assert cls.compute_billable_hours(items, "max") == 8.0
    assert cls.compute_billable_hours(items, "sum") == 8.0


def test_empty_items_zero():
    assert cls.compute_billable_hours([], "max") == 0.0


def test_mixed_freelance_and_internal_sum():
    items = [(1, HUM, 8.0), (2, FRE, 6.0)]
    assert cls.compute_billable_hours(items, "sum") == 14.0


# ── Endpoint /planning/api/bookings/preview-billable (Task 3) ───────────
#
# Adattamenti vs placeholder del piano:
#  - La suite non ha un fixture `db_session` né `client_admin`. La conftest
#    espone solo `db` (SQLite in-memory monouso) e nessun test fa login HTTP.
#  - L'app ha un middleware `auth_guard` che richiede un `access_token` cookie
#    valido (JWT) e un utente attivo. Il middleware risolve l'utente via la sua
#    PROPRIA `app.database.SessionLocal` (NON via la dependency `get_db`), quindi
#    un semplice override di `get_db` non basta. Il fixture `client_admin` qui
#    sotto crea un engine in-memory dedicato, lo aggancia sia a
#    `app.database.engine`/`SessionLocal` (per il middleware) sia all'override di
#    `get_db` (per l'endpoint), seed di un admin + Role, e setta il cookie JWT.
#  - `two_humans` usa la stessa sessione del client così che le Resource create
#    siano visibili all'endpoint. Resource con tenant_id=1 (= CURRENT_TENANT).
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
    from app.models import User, Role
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

    # Seed: ruolo admin (manage_roles → is_admin True) + utente attivo.
    admin_role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["manage_roles"], is_system=True, is_active=True,
    )
    session.add(admin_role)
    session.flush()
    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin Test",
        hashed_password="x", role_id=admin_role.id, is_active=True,
    )
    session.add(admin)
    session.commit()

    from app.database import get_db

    def _override_get_db():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    token = create_access_token({"sub": admin.email, "tid": 1})
    try:
        # httpx 0.28: il Cookie header sui default del client è il modo più
        # affidabile per inviare l'auth a ogni request (set_cookie sull'istanza
        # richiede un domain match con `testserver`).
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"}) as c:
            c.session = session  # comodo per i fixture dati
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


@pytest.fixture
def two_humans(client_admin):
    from app.models import Resource, ResourceType
    s = client_admin.session
    r1 = Resource(tenant_id=1, name="Carlo", type=ResourceType.person_internal, is_active=True)
    r2 = Resource(tenant_id=1, name="Mario", type=ResourceType.person_internal, is_active=True)
    s.add_all([r1, r2])
    s.commit()
    s.refresh(r1)
    s.refresh(r2)
    return r1.id, r2.id


def _assignments_json(rid1, rid2):
    return json.dumps([
        {"resource_id": rid1, "start_datetime": "2026-06-10T09:00:00", "end_datetime": "2026-06-10T17:00:00"},  # 8h
        {"resource_id": rid2, "start_datetime": "2026-06-10T09:00:00", "end_datetime": "2026-06-10T15:00:00"},  # 6h
    ])


def test_preview_billable_max(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2), "billable_hours_mode": "max"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["billable_hours"] == 8.0
    assert body["human_count"] == 2
    assert len(body["breakdown"]) == 2


def test_preview_billable_sum(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2), "billable_hours_mode": "sum"})
    assert resp.status_code == 200
    assert resp.json()["billable_hours"] == 14.0


def test_preview_billable_specific(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2), "billable_hours_mode": "specific",
        "billable_hours_resource_id": r2})
    assert resp.status_code == 200
    assert resp.json()["billable_hours"] == 6.0


def test_preview_billable_manual(client_admin, two_humans):
    r1, r2 = two_humans
    resp = client_admin.post("/planning/api/bookings/preview-billable", data={
        "assignments": _assignments_json(r1, r2), "billable_hours_mode": "manual",
        "billable_hours_manual": 5.0})
    assert resp.status_code == 200
    assert resp.json()["billable_hours"] == 5.0
