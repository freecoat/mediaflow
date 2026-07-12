"""Task 2 — media_library serializer: righe digitali + filtri base (Fase A)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import (
    Base, Tenant, Client, Project, Asset, AssetType, AssetProposedState, User, UserRole,
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
    db.commit()

    return {
        "db": db, "admin": admin, "project": project, "client": client,
        "a_mov": a_mov, "b_wav": b_wav, "pending_mov": pending_mov,
        "other_tenant_asset": other_tenant_asset,
    }


def test_list_digital_basic(ctx):
    db, admin = ctx["db"], ctx["admin"]
    rows = media_library.list_assets(db, admin, {})["rows"]
    assert all(r["nature"] == "digital" for r in rows)
    assert {r["name"] for r in rows} == {"a.mov", "b.wav"}


def test_filter_project(ctx):
    db, admin, project = ctx["db"], ctx["admin"], ctx["project"]
    out = media_library.list_assets(db, admin, {"project_id": project.id})
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
    assert all(r["id"] != other_id for r in rows)
