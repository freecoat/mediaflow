"""F4 (spec 2026-06-11) — Test integrazione endpoint MHL→membership,
catalog CSV, memberships list, tickets CRUD.

Copertura:
  1. POST /ingest/yoyotta-mhl → response["membership"] + 2 AssetMembership in DB
  2. POST /physical-assets/api/{id}/catalog-csv → stats validi / 404 / 400
  3. GET  /physical-assets/api/{id}/memberships → lista con filename / None
  4. GET  /storage/api/tickets → lista + filtro status
  5. POST /storage/api/tickets → ok / kind invalido / asset inesistente
  6. POST /storage/api/tickets/{id}/transition → ok / transizione illegale
  7. Cross-tenant → 404 su transition
"""
import io
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import (
    Base,
    Asset, AssetType, AssetMembership,
    ArchiveTicket,
    Client,
    Job, JobDeliverable,
    PhysicalAsset, PhysicalAssetKind, AssetOwnerType,
    Project,
    StorageVolume,
    Tenant,
    User, UserRole,
)
from app.models import Role


# ── MHL sintetico helper ──────────────────────────────────────────────────────

def _make_mhl(entries: list[dict]) -> bytes:
    """Genera un MHL v1 (hashlist) sintetico con le entry specificate.

    Ogni entry: {filename, checksum (xxhash64), size (int, opz)}.
    """
    parts = ["<?xml version='1.0' encoding='UTF-8'?>", "<hashlist>",
             "<creatorinfo><tool>Yoyotta</tool></creatorinfo>"]
    for e in entries:
        size_tag = f"<size>{e['size']}</size>" if e.get("size") else ""
        checksum_tag = (
            f"<xxhash64>{e['checksum']}</xxhash64>" if e.get("checksum") else ""
        )
        parts.append(
            f"<hash><file>{e['filename']}</file>"
            f"{size_tag}{checksum_tag}</hash>"
        )
    parts.append("</hashlist>")
    return "\n".join(parts).encode()


# ── Fixture client_admin ───────────────────────────────────────────────────────

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

    # Tenant 1 (default)
    session.add(Tenant(id=1, name="TestCo", slug="testco", is_active=True))
    session.flush()

    role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["edit_planning_all", "edit_deliverables",
                     "assign_resources"],
        is_system=True, is_active=True,
    )
    session.add(role)
    session.flush()

    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin User",
        hashed_password="x", role=UserRole.admin, role_id=role.id,
        is_active=True,
    )
    session.add(admin)
    session.flush()

    # Client + Project + Job (richiesti da _process_ingest)
    cli = Client(tenant_id=1, name="ClienteTest")
    session.add(cli)
    session.flush()

    proj = Project(tenant_id=1, code="PROJ001", title="Progetto Test",
                   client_id=cli.id)
    session.add(proj)
    session.flush()

    job = Job(tenant_id=1, code="JOB001", title="Job Test",
              project_id=proj.id, client_id=cli.id)
    session.add(job)
    session.flush()

    # Asset digitale con checksum noto (per match)
    vol = StorageVolume(tenant_id=1, name="SAN", mount_path="/mnt/san")
    session.add(vol)
    session.flush()

    known_asset = Asset(
        tenant_id=1,
        filename="feature_2k.mxf",
        original_name="feature_2k.mxf",
        file_path="OUT/feature_2k.mxf",
        file_size=1_000_000_000,
        mime_type="application/mxf",
        asset_type=AssetType.video,
        uploaded_by=admin.id,
        checksum_xxhash="AABBCCDD11223344",
    )
    session.add(known_asset)
    session.flush()

    # Tape LTO già esistente (per endpoint catalog-csv e memberships)
    tape = PhysicalAsset(
        tenant_id=1,
        project_id=proj.id,
        kind=PhysicalAssetKind.lto,
        label="LTO #001 - Test",
        owner_type=AssetOwnerType.internal,
        is_internal_archive=True,
        logistics_status="in_storage",
        qr_code_token="testtoken001",
    )
    session.add(tape)
    session.flush()

    session.commit()

    # Esponi oggetti utili tramite attributo sul client
    session._test_admin_id = admin.id
    session._test_job_id = job.id
    session._test_proj_id = proj.id
    session._test_cli_id = cli.id
    session._test_known_asset_id = known_asset.id
    session._test_known_checksum = "AABBCCDD11223344"
    session._test_tape_id = tape.id

    def _override():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override
    token = create_access_token({"sub": "admin@test.local", "tid": 1})
    try:
        with TestClient(main_mod.app,
                        headers={"Cookie": f"access_token={token}"},
                        follow_redirects=False) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


# ── Test 1: POST /ingest/yoyotta-mhl ─────────────────────────────────────────

def test_ingest_mhl_membership_stats(client_admin):
    """MHL con 2 file: 1 con checksum noto (matched), 1 sconosciuto (orphan)."""
    session = client_admin.session
    known_checksum = session._test_known_checksum
    job_id = session._test_job_id

    mhl_bytes = _make_mhl([
        {"filename": "feature_2k.mxf", "checksum": known_checksum, "size": 1_000_000_000},
        {"filename": "audio_51.wav",   "checksum": "DEADBEEF99887766"},
    ])

    resp = client_admin.post(
        "/ingest/yoyotta-mhl",
        data={"job_id": job_id},
        files={"file": ("test.mhl", io.BytesIO(mhl_bytes), "text/xml")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "membership" in body
    stats = body["membership"]
    assert stats["matched"] == 1
    assert stats["orphan"] == 1
    assert stats["skipped"] == 0

    # Verifica DB: 2 AssetMembership per il PhysicalAsset creato
    pa_id = body["physical_asset_id"]
    from sqlalchemy import select as _sel
    from app.models.models import AssetMembership as AM
    memberships = session.execute(
        _sel(AM).where(AM.physical_asset_id == pa_id)
    ).scalars().all()
    assert len(memberships) == 2
    matched = [m for m in memberships if m.asset_id is not None]
    orphans = [m for m in memberships if m.asset_id is None]
    assert len(matched) == 1
    assert len(orphans) == 1
    assert matched[0].asset_id == session._test_known_asset_id


# ── Test 2: POST /physical-assets/api/{id}/catalog-csv ───────────────────────

def _make_csv(rows: list[tuple]) -> bytes:
    """rows: [(filename, checksum, size_bytes), ...]"""
    lines = ["filename,checksum,size_bytes"]
    for fn, cs, sz in rows:
        lines.append(f"{fn},{cs},{sz}")
    return "\n".join(lines).encode()


def test_catalog_csv_valid(client_admin):
    session = client_admin.session
    tape_id = session._test_tape_id
    known_checksum = session._test_known_checksum

    csv_bytes = _make_csv([
        ("feature_2k.mxf", known_checksum, 1_000_000_000),
        ("unknown_file.dpx", "FFFF0000FFFF0000", 500_000_000),
    ])
    resp = client_admin.post(
        f"/physical-assets/api/{tape_id}/catalog-csv",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["matched"] == 1
    assert body["orphan"] == 1
    assert body["skipped"] == 0


def test_catalog_csv_not_found(client_admin):
    csv_bytes = _make_csv([("a.mxf", "AA", 100)])
    resp = client_admin.post(
        "/physical-assets/api/99999/catalog-csv",
        files={"file": ("catalog.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 404


def test_catalog_csv_bad_header(client_admin):
    """CSV senza colonna 'filename' risolvibile → 400."""
    session = client_admin.session
    tape_id = session._test_tape_id

    csv_no_filename = b"hash,size\nAABBCC,1000\n"
    resp = client_admin.post(
        f"/physical-assets/api/{tape_id}/catalog-csv",
        files={"file": ("bad.csv", io.BytesIO(csv_no_filename), "text/csv")},
    )
    assert resp.status_code == 400


# ── Test 3: GET /physical-assets/api/{id}/memberships ────────────────────────

def test_list_memberships(client_admin):
    """Dopo l'ingest CSV, la GET /memberships ritorna filename per la
    membership matchata e None per l'orfana."""
    session = client_admin.session
    tape_id = session._test_tape_id
    known_checksum = session._test_known_checksum

    # Popola prima con un CSV
    csv_bytes = _make_csv([
        ("feature_2k.mxf", known_checksum, 1_000_000_000),
        ("orphan.mxf",     "FFFFFFFFFFFFFFFF", 200_000_000),
    ])
    r = client_admin.post(
        f"/physical-assets/api/{tape_id}/catalog-csv",
        files={"file": ("c.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert r.status_code == 200

    resp = client_admin.get(f"/physical-assets/api/{tape_id}/memberships")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 2

    matched = next((i for i in items if i["asset_id"] is not None), None)
    orphan  = next((i for i in items if i["asset_id"] is None), None)
    assert matched is not None
    assert matched["filename"] == "feature_2k.mxf"
    assert orphan is not None
    assert orphan["filename"] is None

    # Verifica shape
    for item in items:
        assert "id" in item
        assert "path_on_media" in item
        assert "file_size" in item
        assert "checksum" in item
        assert "added_at" in item


# ── Test 4: GET /storage/api/tickets ─────────────────────────────────────────

def test_list_tickets_empty(client_admin):
    resp = client_admin.get("/storage/api/tickets")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_tickets_with_filter(client_admin):
    session = client_admin.session
    asset_id = session._test_known_asset_id

    # Crea un ticket via POST
    r = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "restore", "asset_id": asset_id, "note": "Test nota"},
    )
    assert r.status_code == 200

    # Filtro status=requested → deve trovarlo
    resp = client_admin.get("/storage/api/tickets?status=requested")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert all(i["status"] == "requested" for i in items)

    # Filtro status=done → vuoto (nessuno chiuso ancora)
    resp2 = client_admin.get("/storage/api/tickets?status=done")
    assert resp2.status_code == 200
    assert resp2.json() == []


# ── Test 5: POST /storage/api/tickets ────────────────────────────────────────

def test_create_ticket_restore_ok(client_admin):
    session = client_admin.session
    asset_id = session._test_known_asset_id

    resp = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "restore", "asset_id": asset_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["id"], int)


def test_create_ticket_invalid_kind(client_admin):
    session = client_admin.session
    asset_id = session._test_known_asset_id

    resp = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "invalid_kind", "asset_id": asset_id},
    )
    assert resp.status_code == 400


def test_create_ticket_no_target(client_admin):
    """Nessun asset né deliverable → 400 da service."""
    resp = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "archive"},
    )
    assert resp.status_code == 400


def test_create_ticket_asset_not_found(client_admin):
    resp = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "restore", "asset_id": 99999},
    )
    assert resp.status_code == 404


# ── Test 6: POST /storage/api/tickets/{id}/transition ────────────────────────

def test_transition_restore_to_done(client_admin):
    session = client_admin.session
    asset_id = session._test_known_asset_id

    # Crea ticket
    r = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "restore", "asset_id": asset_id},
    )
    assert r.status_code == 200
    ticket_id = r.json()["id"]

    # Transizione requested → done
    resp = client_admin.post(
        f"/storage/api/tickets/{ticket_id}/transition",
        data={"status": "done"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["status"] == "done"


def test_transition_illegal(client_admin):
    session = client_admin.session
    asset_id = session._test_known_asset_id

    # Crea ticket e portalo a done
    r = client_admin.post(
        "/storage/api/tickets",
        data={"kind": "restore", "asset_id": asset_id},
    )
    ticket_id = r.json()["id"]
    client_admin.post(
        f"/storage/api/tickets/{ticket_id}/transition",
        data={"status": "done"},
    )

    # Tenta una seconda transizione da done → illegale
    resp = client_admin.post(
        f"/storage/api/tickets/{ticket_id}/transition",
        data={"status": "done"},
    )
    assert resp.status_code == 400


# ── Test 7: Cross-tenant su ticket ──────────────────────────────────────────

def test_cross_tenant_ticket_transition(client_admin):
    """Ticket di tenant 2 non accessibile da client tenant 1."""
    session = client_admin.session

    # Inserisci direttamente un ticket di tenant 2
    ticket_t2 = ArchiveTicket(
        tenant_id=2,
        kind="restore",
        status="requested",
    )
    session.add(ticket_t2)
    session.commit()

    resp = client_admin.post(
        f"/storage/api/tickets/{ticket_t2.id}/transition",
        data={"status": "done"},
    )
    assert resp.status_code == 404
