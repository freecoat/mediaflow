# tests/test_calendar_api.py
import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Acquisition, AcquisitionStage
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="manager", name="Mgr",
                permissions=["view_calendar", "manage_calendar", "view_acquisitions", "manage_acquisitions"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.manager, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Lucky")); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_create_list_update_delete_event(client):
    c, s = client
    r = c.post("/calendar/api/events", data={
        "title": "Call cliente", "start_at": "2026-07-10T10:00:00",
        "end_at": "2026-07-10T11:00:00", "client_id": "1"})
    assert r.status_code in (200, 201), r.text
    eid = r.json()["id"]
    lst = c.get("/calendar/api/events", params={"start": "2026-07-01", "end": "2026-07-31"}).json()
    assert any(ev["id"] == eid for ev in lst["events"])
    ev = next(ev for ev in lst["events"] if ev["id"] == eid)
    assert ev["title"] == "Call cliente"
    assert ev["client_id"] == 1
    r2 = c.put(f"/calendar/api/events/{eid}", data={"title": "Call rinviata"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["title"] == "Call rinviata"
    assert c.delete(f"/calendar/api/events/{eid}").status_code == 200
    lst2 = c.get("/calendar/api/events", params={"start": "2026-07-01", "end": "2026-07-31"}).json()
    assert all(ev["id"] != eid for ev in lst2["events"])


def test_list_range_excludes_outside(client):
    c, _ = client
    c.post("/calendar/api/events", data={"title": "Luglio", "start_at": "2026-07-15T09:00:00",
           "end_at": "2026-07-15T10:00:00"})
    out = c.get("/calendar/api/events", params={"start": "2026-08-01", "end": "2026-08-31"}).json()
    assert all(ev["title"] != "Luglio" for ev in out["events"])


def test_markers_from_acquisition_close_date(client):
    c, s = client
    # NB: colonne reali sono tipizzate (stage=AcquisitionStage, expected_close_date=date),
    # non stringhe grezze come nella bozza — costruttore ORM diretto richiede i tipi Python reali.
    s.add(Acquisition(id=1, tenant_id=1, title="Deal", stage=AcquisitionStage.lead,
                      expected_close_date=date(2026, 7, 20), is_active=True)); s.commit()
    r = c.get("/calendar/api/events", params={"start": "2026-07-01", "end": "2026-07-31"}).json()
    assert any(m.get("kind") == "acquisition_close" for m in r["markers"])


def test_create_requires_manage_permission(client, monkeypatch):
    c, s = client
    from app.models.models import Role
    role = s.query(Role).first()
    role.permissions = ["view_calendar"]  # solo view, no manage
    s.commit()
    r = c.post("/calendar/api/events", data={"title": "X", "start_at": "2026-07-10T10:00:00",
               "end_at": "2026-07-10T11:00:00"})
    assert r.status_code == 403
