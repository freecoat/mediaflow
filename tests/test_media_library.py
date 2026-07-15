"""Task 2 — media_library serializer: righe digitali + filtri base (Fase A)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base, Tenant, Client, Project, Asset, AssetType, AssetProposedState, User, UserRole,
    PhysicalAsset, PhysicalAssetKind,
    Department, PriceCategory, PriceItem, JobDeliverable, DeliverableAsset,
    DeliverableStatus, DeliverableNature,
)
from app.services import media_library

PRJ_CODE = "PRJ001"


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.fixture
def ctx():
    """Crea Tenant(1), Client, Project(code=PRJ001), utente admin, e gli
    Asset digitali usati dai test. Ritorna dict con session/oggetti utili."""
    db = _session()

    db.add(Tenant(id=1, name="Tenant 1", slug="t1"))
    db.add(Tenant(id=2, name="Tenant 2", slug="t2"))
    db.flush()

    client = Client(tenant_id=1, name="Cliente Uno")
    db.add(client)
    db.flush()

    project = Project(tenant_id=1, code=PRJ_CODE, title="Progetto Uno", client_id=client.id)
    db.add(project)
    db.flush()

    admin = User(
        id=1, tenant_id=1, email="admin@t.local", full_name="Admin",
        hashed_password="x", role=UserRole.admin, is_active=True,
    )
    db.add(admin)
    db.flush()

    now = datetime.now(UTC).replace(tzinfo=None)

    a_mov = Asset(
        tenant_id=1, filename="a.mov", original_name="a.mov", file_path="/vol/a.mov",
        file_size=100, mime_type="video/quicktime", asset_type=AssetType.video,
        uploaded_by=admin.id, project_id=project.id,
        proposed_state=AssetProposedState.confirmed, created_at=now,
        tech_specs_json={"video": {"width": 3840, "height": 2160,
                                   "codec": "hevc", "framerate": "25"}, "audio": []},
    )
    b_wav = Asset(
        tenant_id=1, filename="b.wav", original_name="b.wav", file_path="/vol/b.wav",
        file_size=200, mime_type="audio/wav", asset_type=AssetType.audio,
        uploaded_by=admin.id, project_id=project.id,
        proposed_state=AssetProposedState.confirmed, created_at=now + timedelta(seconds=1),
    )
    pending_mov = Asset(
        tenant_id=1, filename="pending.mov", original_name="pending.mov", file_path="/vol/pending.mov",
        file_size=50, mime_type="video/quicktime", asset_type=AssetType.video,
        uploaded_by=admin.id, project_id=project.id,
        proposed_state=AssetProposedState.pending_review, created_at=now + timedelta(seconds=2),
    )
    other_tenant_asset = Asset(
        tenant_id=2, filename="other.mov", original_name="other.mov", file_path="/vol/other.mov",
        file_size=10, mime_type="video/quicktime", asset_type=AssetType.video,
        uploaded_by=admin.id, project_id=None,
        proposed_state=AssetProposedState.confirmed, created_at=now,
    )
    db.add_all([a_mov, b_wav, pending_mov, other_tenant_asset])
    db.flush()

    # Task 3 — asset fisici (PhysicalAsset). LTO + HDD nel progetto tenant 1,
    # più uno soft-deleted (deleted_at) che NON deve apparire, e uno di tenant 2.
    lto = PhysicalAsset(
        tenant_id=1, kind=PhysicalAssetKind.lto, label="LTO-001",
        serial_number="LTO0001SN", location="Cassaforte", capacity_gb=18000,
        project_id=project.id, created_at=now + timedelta(seconds=3),
    )
    hdd = PhysicalAsset(
        tenant_id=1, kind=PhysicalAssetKind.hdd, label="HDD-Backup",
        serial_number="HDD0001SN", location="Scaffale A", capacity_gb=8000,
        project_id=project.id, created_at=now + timedelta(seconds=4),
    )
    lto_deleted = PhysicalAsset(
        tenant_id=1, kind=PhysicalAssetKind.lto, label="LTO-DEL",
        project_id=project.id, created_at=now + timedelta(seconds=5),
        deleted_at=now + timedelta(seconds=6),
    )
    other_tenant_phys = PhysicalAsset(
        tenant_id=2, kind=PhysicalAssetKind.hdd, label="HDD-OTHER",
        project_id=None, created_at=now,
    )
    db.add_all([lto, hdd, lto_deleted, other_tenant_phys])
    db.flush()

    # Task 4 — catena delivery: Department → PriceItem → JobDeliverable(delivered)
    # → DeliverableAsset che linka a_mov. Serve per linked_to_delivery/status/dept.
    dept = Department(tenant_id=1, code="DI-VIDEO", name="DI / Video")
    db.add(dept)
    db.flush()
    cat = PriceCategory(tenant_id=1, name="Color")
    db.add(cat)
    db.flush()
    pi = PriceItem(tenant_id=1, category_id=cat.id, name="Color HDR",
                   unit="day", department_id=dept.id)
    db.add(pi)
    db.flush()
    jd = JobDeliverable(tenant_id=1, job_id=1, name="DCP INTEROP", price_item_id=pi.id,
                        nature=DeliverableNature.digital, status=DeliverableStatus.delivered)
    db.add(jd)
    db.flush()
    da = DeliverableAsset(tenant_id=1, job_deliverable_id=jd.id, asset_id=a_mov.id)
    db.add(da)
    db.commit()

    return {
        "db": db, "admin": admin, "project": project, "client": client,
        "a_mov": a_mov, "b_wav": b_wav, "pending_mov": pending_mov,
        "other_tenant_asset": other_tenant_asset,
        "lto": lto, "hdd": hdd, "lto_deleted": lto_deleted,
        "other_tenant_phys": other_tenant_phys,
        "dept": dept, "job_deliverable": jd,
    }


def test_list_digital_basic(ctx):
    db, admin = ctx["db"], ctx["admin"]
    rows = media_library.list_assets(db, admin, {"nature": "digital"})["rows"]
    assert all(r["nature"] == "digital" for r in rows)
    assert {r["name"] for r in rows} == {"a.mov", "b.wav"}


def test_filter_project(ctx):
    db, admin, project = ctx["db"], ctx["admin"], ctx["project"]
    out = media_library.list_assets(db, admin, {"nature": "digital", "project_id": project.id})
    assert out["total"] == 2


def test_filter_asset_type(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"asset_type": "video"})
    assert [r["name"] for r in out["rows"]] == ["a.mov"]


def test_filter_q_name(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"q": "wav"})
    assert [r["name"] for r in out["rows"]] == ["b.wav"]


def test_default_hides_pending_proposals(ctx):
    db, admin = ctx["db"], ctx["admin"]
    names = {r["name"] for r in media_library.list_assets(db, admin, {})["rows"]}
    assert "pending.mov" not in names


def test_filter_proposed_pending(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"proposed_state": "pending_review"})
    assert "pending.mov" in {r["name"] for r in out["rows"]}


def test_tenant_scope(ctx):
    db, admin, other_id = ctx["db"], ctx["admin"], ctx["other_tenant_asset"].id
    rows = media_library.list_assets(db, admin, {})["rows"]
    assert all(not (r["nature"] == "digital" and r["id"] == other_id) for r in rows)


# ── Task 3 — physical + merge + paginazione ────────────────────────────────

def test_list_physical(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"nature": "physical"})
    assert all(r["nature"] == "physical" for r in out["rows"])
    names = {r["name"] for r in out["rows"]}
    assert "LTO-001" in names
    assert "HDD-Backup" in names


def test_physical_soft_delete_hidden(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"nature": "physical"})
    assert "LTO-DEL" not in {r["name"] for r in out["rows"]}


def test_physical_tenant_scope(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"nature": "physical"})
    assert "HDD-OTHER" not in {r["name"] for r in out["rows"]}


def test_nature_both_merges(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {})
    natures = {r["nature"] for r in out["rows"]}
    assert natures == {"digital", "physical"}
    # 2 digital confirmed + 2 physical attivi = 4
    assert out["total"] == 4


def test_physical_kind_filter(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"nature": "physical", "physical_kind": "lto"})
    assert all(r["physical_kind"] == "lto" for r in out["rows"])
    assert "LTO-001" in {r["name"] for r in out["rows"]}
    assert "HDD-Backup" not in {r["name"] for r in out["rows"]}


def test_pagination(ctx):
    db, admin = ctx["db"], ctx["admin"]
    p1 = media_library.list_assets(db, admin, {}, offset=0, limit=2)
    assert len(p1["rows"]) == 2 and p1["next_offset"] == 2
    p2 = media_library.list_assets(db, admin, {}, offset=2, limit=2)
    overlap = ({(r["nature"], r["id"]) for r in p1["rows"]}
               & {(r["nature"], r["id"]) for r in p2["rows"]})
    assert not overlap


# ── Task 4 — delivery link/status + department + tech-specs ────────────────

def test_linked_to_delivery(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"linked_to_delivery": "yes"})
    r = next(x for x in out["rows"] if x["name"] == "a.mov")
    assert r["linked_to_delivery"] is True
    assert r["delivery_status"] == "delivered"
    out2 = media_library.list_assets(db, admin, {"linked_to_delivery": "no"})
    assert "a.mov" not in {x["name"] for x in out2["rows"]}


def test_delivery_status_filter(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"delivery_status": "delivered"})
    assert "a.mov" in {x["name"] for x in out["rows"]}
    assert all(r["delivery_status"] == "delivered" for r in out["rows"])


def test_department_populated_and_filter(ctx):
    db, admin, dept = ctx["db"], ctx["admin"], ctx["dept"]
    out = media_library.list_assets(db, admin, {"linked_to_delivery": "yes"})
    r = next(x for x in out["rows"] if x["name"] == "a.mov")
    assert r["department"] == {"id": dept.id, "name": "DI / Video"}
    out2 = media_library.list_assets(db, admin, {"department_id": dept.id})
    assert "a.mov" in {x["name"] for x in out2["rows"]}
    assert "b.wav" not in {x["name"] for x in out2["rows"]}


def test_tech_resolution_filter(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"tech_resolution": "3840x2160"})
    assert "a.mov" in {r["name"] for r in out["rows"]}
    assert "b.wav" not in {r["name"] for r in out["rows"]}


def test_tech_codec_filter(ctx):
    db, admin = ctx["db"], ctx["admin"]
    out = media_library.list_assets(db, admin, {"tech_codec": "hevc"})
    assert "a.mov" in {r["name"] for r in out["rows"]}


# ── Task 5 — opzioni filtri + dettaglio asset ──────────────────────────────

def test_filter_options(ctx):
    db, admin = ctx["db"], ctx["admin"]
    opt = media_library.filter_options(db, admin)
    assert any(p["code"] == "PRJ001" for p in opt["projects"])
    assert any(c["name"] == "Cliente Uno" for c in opt["clients"])
    assert "video" in opt["asset_types"]
    assert "lto" in opt["physical_kinds"]
    assert "delivered" in opt["delivery_statuses"]
    assert any(d["name"] == "DI / Video" for d in opt["departments"])
    assert "3840x2160" in opt["tech"]["resolution"]
    assert "hevc" in opt["tech"]["codec"]


def test_asset_detail_digital(ctx):
    db, admin = ctx["db"], ctx["admin"]
    d = media_library.asset_detail(db, admin, "digital", ctx["a_mov"].id)
    assert d is not None
    assert d["name"] == "a.mov"
    assert d["linked_to_delivery"] is True
    assert d["deliverables"][0]["status"] == "delivered"
    assert d["tech_specs_json"]["video"]["codec"] == "hevc"


def test_asset_detail_physical(ctx):
    db, admin = ctx["db"], ctx["admin"]
    d = media_library.asset_detail(db, admin, "physical", ctx["lto"].id)
    assert d is not None and d["name"] == "LTO-001"


def test_asset_detail_denied_other_tenant(ctx):
    db, admin = ctx["db"], ctx["admin"]
    assert media_library.asset_detail(db, admin, "digital", ctx["other_tenant_asset"].id) is None
    assert media_library.asset_detail(db, admin, "physical", ctx["other_tenant_phys"].id) is None


def test_asset_detail_soft_deleted_physical_none(ctx):
    db, admin = ctx["db"], ctx["admin"]
    assert media_library.asset_detail(db, admin, "physical", ctx["lto_deleted"].id) is None
