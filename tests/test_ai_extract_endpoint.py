"""Tests for POST /delivery-templates/api/{tid}/items/ai-extract
using resolver + strong model (Task 3 — item-parser robusto).
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, User, Role, Tenant, UserRole, DeliveryTemplate
from app.services.auth import create_access_token


@pytest.fixture
def client_admin_extract(monkeypatch, tmp_path):
    """StaticPool in-memory fixture wired to ai-extract endpoint."""
    import app.database as database
    import app.main as main_mod
    from app.database import get_db
    import app.services.capitolato_storage as cs
    import app.services.ai_provider as ai
    import app.services.deliverables_parser as dp
    import app.services.delivery_items_parser as dip

    # redirect upload dir to tmp
    monkeypatch.setattr(cs, "UPLOAD_DIR", tmp_path / "up")

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
    session.add(Tenant(id=1, name="T", slug="t", is_active=True))
    session.flush()
    role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["edit_settings", "edit_delivery_items"],
        is_system=True, is_active=True,
    )
    session.add(role)
    session.flush()
    admin = User(
        tenant_id=1, email="a@t.local", full_name="A",
        hashed_password="x", role=UserRole.admin,
        role_id=role.id, is_active=True,
    )
    session.add(admin)
    session.commit()

    main_mod.app.dependency_overrides[get_db] = lambda: session
    token = create_access_token({"sub": admin.email, "tid": 1})

    # monkeypatches — stub all external calls
    fake_provider = object()
    monkeypatch.setattr(
        ai, "pick_parse_provider",
        lambda uid, db, override_provider=None: (fake_provider, "strong", "claude-sonnet-4-6"),
    )
    monkeypatch.setattr(
        dp, "extract_text_from_file",
        lambda b, fn: "item content " * 100,  # > 20 chars
    )
    monkeypatch.setattr(
        dip, "parse_delivery_items_v2",
        lambda text, db, tenant_id=1, provider=None: {
            "items": [{"name": "Item One", "kind": "video"}],
            "pass1_categories": ["video"],
            "parse_meta": {"chunked": False, "n_chunks": 1, "n_items": 1},
        },
    )
    monkeypatch.setattr(
        dip, "materialize_items",
        lambda db, tid, parsed, tenant_id=1: (1, 0),
    )

    try:
        with TestClient(
            main_mod.app,
            headers={"Cookie": f"access_token={token}"},
            follow_redirects=False,
        ) as c:
            yield c, session
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)


def _create_template(session, *, source_document_path=None, source_document_name=None):
    tpl = DeliveryTemplate(
        tenant_id=1,
        code=f"T-{id(source_document_path)}",
        name="Test Tpl",
        version="1.0",
        is_active=True,
        source_document_path=source_document_path,
        source_document_name=source_document_name,
    )
    session.add(tpl)
    session.commit()
    session.refresh(tpl)
    return tpl


# ── happy path: persisted source_document_path ──────────────────────────────

def test_ai_extract_starts_background(client_admin_extract, monkeypatch):
    """α.172.235: l'endpoint risponde 202 running e marca il template, NON
    esegue il parse in modo sincrono (gira in thread)."""
    import app.services.capitolato_storage as cs
    from app.models.models import DeliveryTemplate

    c, session = client_admin_extract
    monkeypatch.setattr(cs, "resolve_capitolato_source",
                        lambda t: (b"%PDF-1.4 fake", "test.pdf"))
    tpl = _create_template(session, source_document_path="data/capitolato_uploads/test.pdf")

    r = c.post(f"/delivery-templates/api/{tpl.id}/items/ai-extract")
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "running"
    # status endpoint riflette lo stato
    s = c.get(f"/delivery-templates/api/{tpl.id}/items/extract-status")
    assert s.status_code == 200
    assert s.json()["status"] in ("running", "done")  # il thread può aver già finito


def test_run_item_extraction_bg_does_work(client_admin_extract, monkeypatch):
    """Il worker sincrono materializza gli item e marca status=done."""
    import app.services.capitolato_storage as cs
    from app.models.models import DeliveryTemplate
    from app.routers.delivery_items import _run_item_extraction_bg

    c, session = client_admin_extract
    monkeypatch.setattr(cs, "resolve_capitolato_source",
                        lambda t: (b"%PDF fake", "x.pdf"))
    tpl = _create_template(session, source_document_path="data/capitolato_uploads/x.pdf")

    _run_item_extraction_bg(tpl.id, user_id=None, tenant_id=1)
    session.expire_all()
    fresh = session.query(DeliveryTemplate).get(tpl.id)
    assert fresh.items_extraction_status == "done"
    assert "aggiunti" in (fresh.items_extraction_msg or "")


def test_ai_extract_409_when_already_running(client_admin_extract, monkeypatch):
    import app.services.capitolato_storage as cs
    c, session = client_admin_extract
    monkeypatch.setattr(cs, "resolve_capitolato_source",
                        lambda t: (b"%PDF fake", "x.pdf"))
    tpl = _create_template(session, source_document_path="data/capitolato_uploads/x.pdf")
    tpl.items_extraction_status = "running"
    session.commit()
    r = c.post(f"/delivery-templates/api/{tpl.id}/items/ai-extract")
    assert r.status_code == 409, r.text


# ── 404 when no source available ────────────────────────────────────────────

def test_bulk_delete_items(client_admin_extract):
    """α.172.235: bulk-delete soft-delete in blocco, ignora id non validi."""
    from app.models.models import DeliveryItem, DeliveryTemplate
    c, session = client_admin_extract
    tpl = _create_template(session)
    ids = []
    for n in ("A", "B", "C"):
        it = DeliveryItem(tenant_id=1, delivery_template_id=tpl.id, name=f"Item {n}",
                          is_active=True)
        session.add(it); session.flush(); ids.append(it.id)
    session.commit()
    csv = f"{ids[0]},{ids[1]},99999"  # 99999 inesistente
    r = c.post("/delivery-items/api/bulk-delete", data={"ids": csv})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == 2
    assert body["requested"] == 3
    session.expire_all()
    assert session.query(DeliveryItem).get(ids[0]).is_active is False
    assert session.query(DeliveryItem).get(ids[2]).is_active is True  # non toccato


def test_bulk_delete_400_no_ids(client_admin_extract):
    c, _ = client_admin_extract
    r = c.post("/delivery-items/api/bulk-delete", data={"ids": ""})
    assert r.status_code == 400


def test_ai_extract_404_no_source(client_admin_extract, monkeypatch):
    """Endpoint returns 404 when resolve_capitolato_source returns None."""
    import app.services.capitolato_storage as cs

    c, session = client_admin_extract

    monkeypatch.setattr(cs, "resolve_capitolato_source", lambda t: None)

    tpl = _create_template(session)  # no source_document_path, no source_document_name
    r = c.post(f"/delivery-templates/api/{tpl.id}/items/ai-extract")
    assert r.status_code == 404, r.text
    assert "sorgente" in r.text.lower() or "nessun" in r.text.lower()


# ── 404 when template does not exist ────────────────────────────────────────

def test_ai_extract_404_unknown_template(client_admin_extract):
    c, _ = client_admin_extract
    r = c.post("/delivery-templates/api/99999/items/ai-extract")
    assert r.status_code == 404, r.text


# ── 503 when no provider configured ────────────────────────────────────────

def test_ai_extract_503_no_provider(client_admin_extract, monkeypatch):
    import app.services.capitolato_storage as cs
    import app.services.ai_provider as ai

    c, session = client_admin_extract

    monkeypatch.setattr(cs, "resolve_capitolato_source",
                        lambda t: (b"%PDF fake", "x.pdf"))
    monkeypatch.setattr(ai, "pick_parse_provider", lambda uid, db, override_provider=None: None)

    tpl = _create_template(session, source_document_path="data/capitolato_uploads/x.pdf")
    r = c.post(f"/delivery-templates/api/{tpl.id}/items/ai-extract")
    assert r.status_code == 503, r.text
