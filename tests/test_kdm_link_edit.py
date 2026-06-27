# tests/test_kdm_link_edit.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole, Client, Project, KdmRequestLink
from app.services.auth import create_access_token


@pytest.fixture
def client():
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    e = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                      poolclass=StaticPool, future=True)
    Base.metadata.create_all(e)
    S = sessionmaker(bind=e, expire_on_commit=False, autoflush=False); s = S()
    s.add(Tenant(id=1, name="T", slug="t", is_active=True)); s.flush()
    role = Role(tenant_id=1, code="admin", name="A", permissions=["manage_kdm"],
                is_system=True, is_active=True)
    s.add(role); s.flush()
    s.add(User(id=1, tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
               role=UserRole.admin, role_id=role.id, is_active=True))
    s.add(Client(id=1, tenant_id=1, name="Arcadia")); s.flush()
    s.add(Project(id=1, tenant_id=1, code="P1", title="Film1", client_id=1)); s.flush()
    s.add(KdmRequestLink(id=1, tenant_id=1, token="tok1", label="Vecchio", is_active=True))
    s.add(KdmRequestLink(id=2, tenant_id=1, token="tok2", label="Revocato", is_active=False))
    s.commit()
    database.engine = e; database.SessionLocal = S
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "a@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_edit_link_updates_fields(client):
    c, s = client
    r = c.put("/kdm/api/links/1", data={"label": "Nuovo", "project_id": "1",
              "duration_days": "30", "prefill_title": "Queer"})
    assert r.status_code == 200, r.text
    s.expire_all()
    lnk = s.get(KdmRequestLink, 1)
    assert lnk.label == "Nuovo"
    assert lnk.project_id == 1
    assert lnk.expires_at is not None
    assert (lnk.prefill_json or {}).get("requested_title") == "Queer"


def test_edit_revoked_link_blocked(client):
    c, _ = client
    r = c.put("/kdm/api/links/2", data={"label": "X"})
    assert r.status_code == 400


def test_edit_unknown_link_404(client):
    c, _ = client
    assert c.put("/kdm/api/links/999", data={"label": "X"}).status_code == 404
