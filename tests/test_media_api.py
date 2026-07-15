"""Task 6 — router /media: page gate + API read (assets/filters/detail).
Pattern JWT-cookie reale + monkeypatch database.engine/SessionLocal
(auth_guard middleware globale risolve l'utente dal cookie prima del router).
Le funzioni media_library sono monkeypatchate: qui si testa il router, non
la logica di query (coperta da test_media_library.py)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base, Tenant, User, UserRole
from app.services.auth import create_access_token
import app.main as main_mod


@pytest.fixture
def client(monkeypatch):
    import app.database as database
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


def _viewer_client(s):
    viewer = User(id=2, tenant_id=1, email="viewer@t.local", full_name="Viewer",
                  hashed_password="x", role=UserRole.viewer, is_active=True)
    s.add(viewer)
    s.commit()
    tok = create_access_token({"sub": "viewer@t.local", "tid": 1})
    return TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"})


def test_media_page_requires_permission(client):
    c, s = client
    vc = _viewer_client(s)
    assert vc.get("/media").status_code in (302, 403)


def test_assets_api_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "list_assets",
                        lambda db, u, f, **k: {"rows": [{"nature": "digital", "id": 1, "name": "x"}],
                                               "total": 1, "next_offset": None})
    r = c.get("/media/api/assets?nature=digital")
    assert r.status_code == 200
    assert r.json()["rows"][0]["id"] == 1


def test_assets_api_denied_viewer(client):
    c, s = client
    vc = _viewer_client(s)
    assert vc.get("/media/api/assets").status_code == 403


def test_filters_api(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "filter_options",
                        lambda db, u: {"projects": [], "asset_types": ["video"]})
    r = c.get("/media/api/filters")
    assert r.status_code == 200
    assert "video" in r.json()["asset_types"]


def test_asset_detail_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "asset_detail",
                        lambda db, u, n, i: {"nature": n, "id": i, "name": "a.mov"})
    r = c.get("/media/api/asset/digital/7")
    assert r.status_code == 200
    assert r.json()["id"] == 7


def test_asset_detail_404(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_library, "asset_detail", lambda db, u, n, i: None)
    assert c.get("/media/api/asset/digital/999").status_code == 404


def test_asset_detail_bad_nature_404(client):
    c, s = client
    assert c.get("/media/api/asset/weird/1").status_code == 404


def test_associate_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "associate",
                        lambda db, u, **k: {"linked": 1, "superseded": 1, "status_reset": True})
    r = c.post("/media/api/associate", data={"deliverable_id": "1",
               "items": '[{"nature":"digital","id":5}]', "reason": "QC"})
    assert r.status_code == 200 and r.json()["superseded"] == 1

def test_associate_bad_items_400(client):
    c, s = client
    r = c.post("/media/api/associate", data={"deliverable_id": "1", "items": "not-json"})
    assert r.status_code == 400

def test_associate_missing_deliverable_404(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    def _raise(db, u, **k):
        raise m.media_actions.MediaActionError("x")
    monkeypatch.setattr(m.media_actions, "associate", _raise)
    r = c.post("/media/api/associate", data={"deliverable_id": "9",
               "items": '[{"nature":"digital","id":5}]'})
    assert r.status_code == 404

def test_flags_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "set_flags", lambda db, u, items, **k: {"updated": 2})
    r = c.post("/media/api/flags", data={"items": '[{"nature":"digital","id":1}]',
               "internal_archive": "1"})
    assert r.status_code == 200 and r.json()["updated"] == 2

def test_unlink_ok(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "unlink", lambda db, u, **k: {"removed": 1})
    r = c.post("/media/api/unlink", data={"deliverable_id": "1",
               "items": '[{"nature":"digital","id":1}]'})
    assert r.status_code == 200 and r.json()["removed"] == 1

def test_export_csv_download(client, monkeypatch):
    c, s = client
    import app.routers.media as m
    monkeypatch.setattr(m.media_actions, "export_manifest_csv", lambda db, u, **k: "nature,name\ndigital,x\n")
    r = c.get("/media/api/export?nature=digital")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")

def test_associate_denied_viewer(client):
    c, s = client
    vc = _viewer_client(s)
    r = vc.post("/media/api/associate", data={"deliverable_id": "1", "items": "[]"})
    assert r.status_code == 403
