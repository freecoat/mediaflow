"""Vincoli specs per tipo file (α.172.183): field_relevance + coerenza."""
from app.services import delivery_item_validation as dv


def test_audio_container_hides_video_and_color():
    g = dv.field_relevance(media_kind="audio", has_package=False,
                           video_codec_family=None, has_audio=True)
    assert g["video"] == "hide"
    assert g["color"] == "hide"
    assert g["audio"] == "show"


def test_image_seq_hides_audio():
    g = dv.field_relevance(media_kind="image_seq", has_package=False,
                           video_codec_family="jpeg2000", has_audio=False)
    assert g["audio"] == "hide"
    assert g["video"] == "show"


def test_video_with_audio_shows_both():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=True)
    assert g["video"] == "show"
    assert g["audio"] == "show"


def test_video_without_audio_hides_audio():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=False)
    assert g["audio"] == "hide"


def test_no_package_hides_package():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=True)
    assert g["package"] == "hide"


def test_with_package_shows_package():
    g = dv.field_relevance(media_kind="video", has_package=True,
                           video_codec_family="jpeg2000", has_audio=False)
    assert g["package"] == "show"


def test_unknown_media_kind_shows_all():
    g = dv.field_relevance(media_kind=None, has_package=False,
                           video_codec_family=None, has_audio=False)
    assert all(v == "show" for k, v in g.items() if k in ("video", "audio", "color"))


# ── Endpoint POST /delivery-items/api/spec-schema (SC-T2) ────────────────
#
# Riusa il fixture `client_admin` di test_billable_hours_mode.py (StaticPool
# in-memory + monkeypatch engine/SessionLocal + JWT cookie + admin seed +
# espone .session). Replicato qui per indipendenza del file.
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_admin(monkeypatch):
    """TestClient autenticato come admin su un DB in-memory isolato."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.models.models import Base
    from app.models import User, Role
    import app.database as database
    import app.main as main_mod
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

    admin_role = Role(
        tenant_id=1, code="admin", name="Admin",
        permissions=["manage_roles"], is_system=True, is_active=True,
    )
    session.add(admin_role)
    session.flush()
    admin = User(
        tenant_id=1, email="admin@test.local", full_name="Admin Test",
        hashed_password="x", role_id=admin_role.id, is_active=True,
    )
    session.add(admin)
    session.commit()

    from app.database import get_db

    def _override_get_db():
        yield session

    main_mod.app.dependency_overrides[get_db] = _override_get_db
    token = create_access_token({"sub": admin.email, "tid": 1})
    try:
        with TestClient(main_mod.app, headers={"Cookie": f"access_token={token}"}) as c:
            c.session = session
            yield c
    finally:
        main_mod.app.dependency_overrides.pop(get_db, None)
        session.close()
        engine.dispose()


@pytest.fixture
def taxo(client_admin):
    s = client_admin.session
    from app.models.models import Container, VideoCodec
    c_audio = Container(tenant_id=1, name="WAV", media_kind="audio")
    c_mxf = Container(tenant_id=1, name="MXF OP1a", media_kind="video", op_pattern="op1a")
    c_mov = Container(tenant_id=1, name="QuickTime", media_kind="video")
    vc_prores = VideoCodec(tenant_id=1, name="ProRes 4444", family="ProRes")
    vc_j2k = VideoCodec(tenant_id=1, name="JPEG2000", family="JPEG2000")
    s.add_all([c_audio, c_mxf, c_mov, vc_prores, vc_j2k]); s.commit()
    for o in (c_audio, c_mxf, c_mov, vc_prores, vc_j2k): s.refresh(o)
    return {"audio": c_audio.id, "mxf": c_mxf.id, "mov": c_mov.id,
            "prores": vc_prores.id, "j2k": vc_j2k.id}


def test_spec_schema_audio_hides_video(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema", data={"container_id": taxo["audio"]})
    assert r.status_code == 200
    assert r.json()["groups"]["video"] == "hide"


def test_spec_schema_prores_in_mxf_warns(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema",
                          data={"container_id": taxo["mxf"], "video_codec_id": taxo["prores"]})
    assert r.status_code == 200
    codes = [f["code"] for f in r.json()["findings"]]
    assert "PRORES_PREFERS_QUICKTIME" in codes


def test_spec_schema_j2k_in_mov_errors(client_admin, taxo):
    r = client_admin.post("/delivery-items/api/spec-schema",
                          data={"container_id": taxo["mov"], "video_codec_id": taxo["j2k"]})
    assert r.status_code == 200
    findings = r.json()["findings"]
    assert any(f["code"] == "J2K_REQUIRES_MXF" and f["severity"] == "error" for f in findings)


# ── Enforcement ERROR su PUT /delivery-items/api/{iid} (SC-T3) ───────────
@pytest.fixture
def prores_item(client_admin, taxo):
    """DeliveryItem valido (ProRes in QuickTime) salvato. Ritorna iid."""
    s = client_admin.session
    from app.models.models import DeliveryItem, DeliveryTemplate
    tpl = DeliveryTemplate(tenant_id=1, code="T1", name="Test")
    s.add(tpl); s.commit(); s.refresh(tpl)
    it = DeliveryItem(tenant_id=1, delivery_template_id=tpl.id, name="Master",
                      container_id=taxo["mov"], video_codec_id=taxo["prores"])
    s.add(it); s.commit(); s.refresh(it)
    return it.id


def test_update_item_blocks_error_combo(client_admin, taxo, prores_item):
    # container QuickTime (mov) + codec J2K → R4 error → 422
    r = client_admin.put(f"/delivery-items/api/{prores_item}",
                         data={"video_codec_id": taxo["j2k"], "container_id": taxo["mov"]})
    assert r.status_code == 422
    assert "J2K_REQUIRES_MXF" in str(r.json())


def test_update_item_allows_valid_combo(client_admin, taxo, prores_item):
    # J2K in MXF → valido → 200
    r = client_admin.put(f"/delivery-items/api/{prores_item}",
                         data={"video_codec_id": taxo["j2k"], "container_id": taxo["mxf"]})
    assert r.status_code == 200


def test_update_item_warning_does_not_block(client_admin, taxo, prores_item):
    # ProRes in MXF → R3 warning → 200
    r = client_admin.put(f"/delivery-items/api/{prores_item}",
                         data={"video_codec_id": taxo["prores"], "container_id": taxo["mxf"]})
    assert r.status_code == 200
