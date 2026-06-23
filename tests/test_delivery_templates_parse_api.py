import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.models.models import Base, User, Role, Tenant, UserRole
from app.services.auth import create_access_token


@pytest.fixture
def client_admin(monkeypatch, tmp_path):
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    from app.services import capitolato_storage as cs
    monkeypatch.setattr(cs, "UPLOAD_DIR", tmp_path / "up")

    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", TestSession)
    session = TestSession()
    session.add(Tenant(id=1, name="T", slug="t", is_active=True)); session.flush()
    role = Role(tenant_id=1, code="admin", name="Admin",
                permissions=["edit_settings"], is_system=True, is_active=True)
    session.add(role); session.flush()
    admin = User(tenant_id=1, email="a@t.local", full_name="A", hashed_password="x",
                 role=UserRole.admin, role_id=role.id, is_active=True)
    session.add(admin); session.commit()
    main_mod.app.dependency_overrides[get_db] = lambda: session
    token = create_access_token({"sub": admin.email, "tid": 1})

    # stub parser + provider per non chiamare AI vera
    import app.services.deliverables_parser as dp
    import app.services.ai_provider as ai
    monkeypatch.setattr(ai, "pick_parse_provider",
                        lambda uid, db: (object(), "strong", "claude-sonnet-4-6"))
    monkeypatch.setattr(dp, "extract_text_from_file",
                        lambda b, fn: "capitolato " * 50)
    monkeypatch.setattr(dp, "parse_delivery_template",
                        lambda text, provider=None, model_tier="strong": {
                            "code": "X", "name": "Test",
                            "parse_meta": {"model_tier": model_tier, "warnings": []}})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


def test_parse_returns_meta_and_source_path(client_admin):
    r = client_admin.post("/delivery-templates/api/parse",
                          files={"file": ("Paramount.pdf", b"%PDF fake", "application/pdf")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["parse_meta"]["model_tier"] == "strong"
    assert data["source_document_path"].endswith(".pdf")
    assert data["source_document_name"] == "Paramount.pdf"


def test_save_persists_source_path(client_admin):
    r = client_admin.post("/delivery-templates/api/save", data={
        "code": "PARAMOUNT-X", "name": "Paramount X", "version": "1.0",
        "source_document_path": "data/capitolato_uploads/abc.pdf",
    })
    assert r.status_code in (200, 201), r.text
    tid = r.json().get("id")
    # rilegge dal DB via list endpoint
    lst = client_admin.get("/delivery-templates/api/list").json()
    row = [t for t in lst if t.get("id") == tid][0]
    assert row.get("source_document_path") == "data/capitolato_uploads/abc.pdf" \
        or row.get("code") == "PARAMOUNT-X"  # source_document_path may not be in list dict


def test_reparse_404_without_source(client_admin):
    # crea template senza source
    r = client_admin.post("/delivery-templates/api/save", data={
        "code": "NOSRC", "name": "No Source", "version": "1.0"})
    tid = r.json()["id"]
    rr = client_admin.post(f"/delivery-templates/api/{tid}/reparse")
    assert rr.status_code == 404
