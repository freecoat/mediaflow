"""Browse storage via agent (spec 2026-06-11).

Parte agent: agent.browse.list_dir — listing puro, dirs-first, cap, traversal guard.
Parte server: POST /storage/api/volumes/{id}/browse (enqueue) + GET /storage/api/jobs/{id} (poll).
"""
import pytest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base
from app.models import User, Role, Tenant
from app.models.models import UserRole, AgentJob, AgentJobType, StorageVolume

from agent.browse import list_dir


# ── agent.browse.list_dir ────────────────────────────────────────────

@pytest.fixture
def tree(tmp_path):
    (tmp_path / "OUT").mkdir()
    (tmp_path / "archive").mkdir()
    (tmp_path / "zfile.mov").write_bytes(b"x" * 10)
    (tmp_path / "a.wav").write_bytes(b"x" * 5)
    (tmp_path / "OUT" / "ep01.mxf").write_bytes(b"y" * 7)
    return tmp_path


def test_list_dir_root_dirs_first_alpha(tree):
    out = list_dir(str(tree), "")
    names = [e["name"] for e in out["entries"]]
    # dirs prima, poi file; alfabetico case-insensitive ("archive" < "OUT")
    assert names == ["archive", "OUT", "a.wav", "zfile.mov"]
    assert out["entries"][0]["is_dir"] is True
    assert out["entries"][0]["size"] is None
    assert out["entries"][2]["is_dir"] is False
    assert out["entries"][2]["size"] == 5
    assert out["truncated"] is False
    assert out["rel_path"] == ""


def test_list_dir_subdir(tree):
    out = list_dir(str(tree), "OUT")
    assert [e["name"] for e in out["entries"]] == ["ep01.mxf"]
    assert out["rel_path"] == "OUT"


def test_list_dir_cap_truncated(tree):
    for i in range(12):
        (tree / f"f{i:02d}.txt").write_text("x")
    out = list_dir(str(tree), "", max_entries=10)
    assert len(out["entries"]) == 10
    assert out["truncated"] is True


def test_list_dir_traversal_blocked(tree):
    with pytest.raises(ValueError):
        list_dir(str(tree), "../")
    with pytest.raises(ValueError):
        list_dir(str(tree), "OUT/../../etc")


def test_list_dir_missing_dir(tree):
    with pytest.raises(FileNotFoundError):
        list_dir(str(tree), "non-esiste")


# ── Server: enqueue browse + poll job ────────────────────────────────

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
    session.add(Tenant(id=1, name="T", slug="t1", is_active=True))
    session.flush()
    role = Role(tenant_id=1, code="admin", name="Admin",
                permissions=["edit_planning_all"], is_system=True, is_active=True)
    session.add(role)
    session.flush()
    session.add(User(tenant_id=1, email="admin@test.local", full_name="Admin",
                     hashed_password="x", role=UserRole.admin, role_id=role.id,
                     is_active=True))
    session.commit()

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    token = create_access_token({"sub": "admin@test.local", "tid": 1})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


def _make_volume(session) -> StorageVolume:
    v = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(v)
    session.commit()
    return v


def test_browse_enqueues_job(client_admin):
    v = _make_volume(client_admin.session)
    r = client_admin.post(f"/storage/api/volumes/{v.id}/browse",
                          data={"rel_path": "/OUT/serie"})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    job = client_admin.session.get(AgentJob, job_id)
    assert job.type == AgentJobType.browse
    assert job.payload == {"volume_id": v.id, "rel_path": "OUT/serie"}


def test_browse_404_unknown_volume(client_admin):
    r = client_admin.post("/storage/api/volumes/9999/browse", data={"rel_path": ""})
    assert r.status_code == 404


def test_get_job_returns_result(client_admin):
    from app.services.agent_queue import enqueue_job
    v = _make_volume(client_admin.session)
    job = enqueue_job(client_admin.session, tenant_id=1,
                      type=AgentJobType.browse,
                      payload={"volume_id": v.id, "rel_path": ""})
    client_admin.session.commit()
    r = client_admin.get(f"/storage/api/jobs/{job.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == job.id
    assert body["status"] == "queued"
    assert body["type"] == "browse"


def test_get_job_404_cross_tenant(client_admin):
    from app.services.agent_queue import enqueue_job
    session = client_admin.session
    session.add(Tenant(id=2, name="T2", slug="t2", is_active=True))
    session.flush()
    job = enqueue_job(session, tenant_id=2, type=AgentJobType.scan,
                      payload={"volume_id": 1})
    session.commit()
    assert client_admin.get(f"/storage/api/jobs/{job.id}").status_code == 404
    assert client_admin.get("/storage/api/jobs/999999").status_code == 404
