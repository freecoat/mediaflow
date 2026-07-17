import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole
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
    s.add(Tenant(id=1, name="T", slug="t", is_active=True))
    s.add(User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
               hashed_password="x", role=UserRole.admin, is_active=True))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_prefs_defaults(client):
    c, s = client
    p = c.get("/mail/api/prefs").json()["prefs"]
    assert p["mark_read_on_open"] is True
    assert p["auto_refresh_sec"] == 120
    assert p["compose_new_window"] is False
    assert p["default_font"]


def test_prefs_save_partial_and_persist(client):
    c, s = client
    r = c.post("/mail/api/prefs", data={"mark_read_on_open": "0", "auto_refresh_sec": 300})
    assert r.status_code == 200 and r.json()["ok"] is True
    p = c.get("/mail/api/prefs").json()["prefs"]
    assert p["mark_read_on_open"] is False
    assert p["auto_refresh_sec"] == 300
    # chiavi non toccate restano al default
    assert p["autosave"] is True


def test_prefs_clamp_refresh(client):
    c, s = client
    c.post("/mail/api/prefs", data={"auto_refresh_sec": 999999})
    assert c.get("/mail/api/prefs").json()["prefs"]["auto_refresh_sec"] == 3600
    c.post("/mail/api/prefs", data={"auto_refresh_sec": -5})
    assert c.get("/mail/api/prefs").json()["prefs"]["auto_refresh_sec"] == 0


def test_compose_page_renders(client):
    c, s = client
    r = c.get("/mail/compose")
    assert r.status_code == 200
    assert "mail-body-editor" in r.text
