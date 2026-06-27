# tests/test_web_sources_api.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole
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
    # Patch engine + SessionLocal so auth middleware uses the test DB
    monkeypatch.setattr(database, "engine", e)
    monkeypatch.setattr(database, "SessionLocal", S)
    s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="admin", name="A",
                permissions=["manage_settings_global"], is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.admin, role_id=role.id, is_active=True)); s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_get_and_set_web_sources(client):
    c, s = client
    r = c.post("/settings/api/web-sources", data={"sources": "filmitalia.org\nimdb.com\n  \nmymovies.it"})
    assert r.status_code == 200, r.text
    assert r.json()["sources"] == ["filmitalia.org", "imdb.com", "mymovies.it"]
    g = c.get("/settings/api/web-sources").json()
    assert g["sources"] == ["filmitalia.org", "imdb.com", "mymovies.it"]
