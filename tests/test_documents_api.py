import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.models.models import Base, Tenant, User, UserRole, Project, Client
from app.services.auth import create_access_token


@pytest.fixture
def client(monkeypatch):
    # NB: la bozza del brief monkeypatchava `current_user`/`current_user_optional`
    # sul modulo app.routers.documents, ma quello NON basta: main.py ha un
    # middleware `auth_guard` globale che risolve l'utente da un vero JWT
    # cookie interrogando `app.database.SessionLocal()` PRIMA che la request
    # arrivi al router — bypassarlo richiede un cookie reale + puntare
    # SessionLocal/engine al DB di test (stesso pattern di test_calendar_api.py,
    # sibling task nella stessa fase).
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
    admin = User(id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
                 hashed_password="x", role=UserRole.admin, is_active=True)
    s.add(admin)
    s.add(Client(id=1, tenant_id=1, name="Cliente"))
    s.add(Project(id=1, tenant_id=1, code="P1", title="Progetto", client_id=1))
    s.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: s
    tok = create_access_token({"sub": "admin@t.local", "tid": 1})
    with TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"}) as c:
        yield c, s
    main_mod.app.dependency_overrides.pop(get_db, None)


def test_link_by_url(client, monkeypatch):
    c, s = client
    from app.services import google_drive as gd
    monkeypatch.setattr(gd, "parse_drive_file_id", lambda u: "ABC")
    monkeypatch.setattr(gd, "fetch_file_metadata", lambda db, uid, fid: {
        "file_id": "ABC", "name": "Contratto.pdf", "mime_type": "application/pdf",
        "web_url": "https://drive.google.com/file/d/ABC/view",
        "icon_url": "https://icon", "owner_email": "o@x.com"})
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "url": "https://drive.google.com/file/d/ABC/view"})
    assert r.status_code == 200
    b = r.json()
    assert b["name"] == "Contratto.pdf"
    assert b["external_file_id"] == "ABC"


def test_link_by_url_non_drive_400(client, monkeypatch):
    c, s = client
    from app.services import google_drive as gd
    monkeypatch.setattr(gd, "parse_drive_file_id", lambda u: None)
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "url": "https://example.com/x"})
    assert r.status_code == 400


def test_link_by_url_fallback_name(client, monkeypatch):
    c, s = client
    from app.services import google_drive as gd
    monkeypatch.setattr(gd, "parse_drive_file_id", lambda u: "ZZZ")
    monkeypatch.setattr(gd, "fetch_file_metadata", lambda db, uid, fid: None)  # 403/non accessibile
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "url": "https://drive.google.com/file/d/ZZZ/view"})
    assert r.status_code == 200
    assert r.json()["name"]  # fallback non vuoto
    assert r.json()["external_file_id"] == "ZZZ"


def test_link_by_picker_payload(client):
    c, s = client
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
               "file_id": "PICK1", "name": "Slide.pptx", "mime_type": "x",
               "web_url": "https://drive.google.com/file/d/PICK1/view", "icon_url": "https://i"})
    assert r.status_code == 200
    assert r.json()["external_file_id"] == "PICK1"


def test_list_filtered(client):
    c, s = client
    c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
           "file_id": "F1", "name": "A", "web_url": "https://drive.google.com/file/d/F1/view"})
    r = c.get("/documents/api/list", params={"linked_type": "project", "linked_id": "1"})
    assert r.status_code == 200
    assert len(r.json()["documents"]) == 1


def test_delete_soft(client):
    c, s = client
    lid = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
                 "file_id": "F2", "name": "B", "web_url": "https://drive.google.com/file/d/F2/view"}).json()["id"]
    r = c.delete(f"/documents/api/link/{lid}")
    assert r.status_code == 200
    r2 = c.get("/documents/api/list", params={"linked_type": "project", "linked_id": "1"})
    assert all(d["id"] != lid for d in r2.json()["documents"])


def test_linked_entity_404(client):
    c, s = client
    r = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "999",
               "file_id": "F3", "name": "C", "web_url": "https://drive.google.com/file/d/F3/view"})
    assert r.status_code == 404


def test_picker_config_disabled_without_key(client, monkeypatch):
    c, s = client
    monkeypatch.delenv("GOOGLE_PICKER_API_KEY", raising=False)
    r = c.get("/documents/api/picker-config")
    assert r.status_code == 200
    assert r.json()["enabled"] is False


# ── RBAC negative-path (403) ─────────────────────────────────────
# Ruolo `viewer` (preset PRESET_PERMISSIONS in app/services/rbac.py) NON ha
# `edit_projects` né `view_acquisitions`/`manage_acquisitions` — ma HA
# `view_projects` (ogni preset built-in ce l'ha, quindi non esiste un ruolo
# "senza view_projects" per testare la 403 sulla list di tipo project).
# Per la 403 sulla list usiamo quindi linked_type=acquisition (stesso branch
# di codice in list_documents(), solo perm_view diverso: view_acquisitions).
import app.main as main_mod


def _viewer_client(s):
    """Crea un secondo utente (ruolo viewer, privilegi minimi) nella STESSA
    sessione di test e ritorna un TestClient autenticato come lui, riusando
    l'app già patchata dalla fixture `client` (stesso pattern JWT-cookie)."""
    viewer = User(id=2, tenant_id=1, email="viewer@t.local", full_name="Viewer",
                  hashed_password="x", role=UserRole.viewer, is_active=True)
    s.add(viewer)
    s.commit()
    tok = create_access_token({"sub": "viewer@t.local", "tid": 1})
    return TestClient(main_mod.app, headers={"Cookie": f"access_token={tok}"})


def test_link_denied_without_manage(client):
    c, s = client
    vc = _viewer_client(s)
    r = vc.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
                "file_id": "V1", "name": "Doc", "web_url": "https://drive.google.com/file/d/V1/view"})
    assert r.status_code == 403


def test_delete_denied_without_manage(client):
    c, s = client
    lid = c.post("/documents/api/link", data={"linked_type": "project", "linked_id": "1",
                 "file_id": "V2", "name": "D", "web_url": "https://drive.google.com/file/d/V2/view"}).json()["id"]
    vc = _viewer_client(s)
    r = vc.delete(f"/documents/api/link/{lid}")
    assert r.status_code == 403
    # non soft-cancellato: resta visibile nella list (admin ha view_projects)
    r2 = c.get("/documents/api/list", params={"linked_type": "project", "linked_id": "1"})
    assert any(d["id"] == lid for d in r2.json()["documents"])


def test_list_denied_without_view(client):
    # viewer manca di view_acquisitions/manage_acquisitions (a differenza di
    # view_projects, presente in TUTTI i preset built-in) → usiamo
    # linked_type=acquisition per esercitare il ramo 403 dell'endpoint list.
    c, s = client
    vc = _viewer_client(s)
    r = vc.get("/documents/api/list", params={"linked_type": "acquisition", "linked_id": "1"})
    assert r.status_code == 403
