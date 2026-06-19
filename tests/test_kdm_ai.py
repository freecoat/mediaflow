# tests/test_kdm_ai.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.models import Base
from app.models import Tenant
from app.services.ai_capability_registry import get_action_types, get_handler


# ---------------------------------------------------------------------------
# In-memory DB fixture (StaticPool pattern — same as test_kdm_router.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session(monkeypatch):
    """In-memory SQLite session for handler tests.

    Handlers use db.flush() (not commit), so all changes land only in this
    session's transaction; teardown is automatic when the fixture exits.
    """
    import app.database as database

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
    # Seed tenant=1 required by KDM models (tenant_id FK)
    session.add(Tenant(id=1, name="Test Tenant", slug="test", is_active=True))
    session.flush()

    yield session

    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# Registry smoke tests (no DB required)
# ---------------------------------------------------------------------------

def test_kdm_capabilities_registered():
    import app.services.ai_assistant  # noqa: F401  (forces registration)
    types = get_action_types()
    assert "propose_kdm_request" in types
    assert "propose_cinema_server" in types
    assert callable(get_handler("propose_kdm_request"))


def test_kdm_handlers_in_action_handlers_snapshot():
    """Regression test for C1: both KDM handlers must be in the production
    dispatch dict (_ACTION_HANDLERS), not just in the live registry.
    This dict is a ONE-SHOT snapshot taken at import time; handlers defined
    after the snapshot are invisible to apply_action (the Applica button).
    """
    import app.services.ai_assistant  # noqa: F401  (forces registration)
    from app.services.ai_assistant import _ACTION_HANDLERS
    assert "propose_cinema_server" in _ACTION_HANDLERS, (
        "propose_cinema_server missing from _ACTION_HANDLERS snapshot — "
        "handler was defined after the snapshot, see C1 fix"
    )
    assert "propose_kdm_request" in _ACTION_HANDLERS, (
        "propose_kdm_request missing from _ACTION_HANDLERS snapshot — "
        "handler was defined after the snapshot, see C1 fix"
    )


# ---------------------------------------------------------------------------
# Handler integration tests (use in-memory DB — no leaks to dev DB)
# ---------------------------------------------------------------------------

def test_propose_cinema_server_creates_facility_and_server(db_session):
    import app.services.ai_assistant  # noqa: F401
    from app.models import CinemaFacility, CinemaServer

    handler = get_handler("propose_cinema_server")
    result = handler(db_session, {
        "facility_name": "UCI Test Cinema",
        "city": "Milano",
        "manufacturer": "dolby",
        "serial": "IMS-AI-TEST-001",
        "kind": "cinema",
    })
    assert "facility_id" in result
    assert "server_id" in result
    assert isinstance(result["facility_id"], int)
    assert isinstance(result["server_id"], int)

    # Verify rows exist in this session (handler flushed, not committed)
    fac = db_session.query(CinemaFacility).filter(CinemaFacility.id == result["facility_id"]).first()
    srv = db_session.query(CinemaServer).filter(CinemaServer.id == result["server_id"]).first()
    assert fac is not None
    assert srv is not None
    # Cleanup: rollback handled by fixture


def test_propose_cinema_server_invalid_kind_falls_back(db_session):
    """m2: invalid kind must be silently normalized to 'cinema'."""
    import app.services.ai_assistant  # noqa: F401
    from app.models import CinemaFacility

    handler = get_handler("propose_cinema_server")
    result = handler(db_session, {
        "facility_name": "Test Kind Guard Cinema",
        "kind": "unknown_garbage_value",
    })
    fac = db_session.query(CinemaFacility).filter(CinemaFacility.id == result["facility_id"]).first()
    assert fac is not None
    assert fac.kind == "cinema", f"Expected 'cinema', got {fac.kind!r}"


def test_propose_kdm_request_creates_request(db_session):
    import app.services.ai_assistant  # noqa: F401
    from app.models import KdmRequest

    handler = get_handler("propose_kdm_request")
    result = handler(db_session, {
        "request_type": "kdm",
        "requested_title": "Test Film AI",
    })
    assert "kdm_request_id" in result
    assert isinstance(result["kdm_request_id"], int)
    assert result["status"] in ("received", "matched")
    assert isinstance(result["candidates"], list)

    # Verify row exists in this session (handler flushed, not committed)
    req = db_session.query(KdmRequest).filter(KdmRequest.id == result["kdm_request_id"]).first()
    assert req is not None
    assert req.request_type == "kdm"
    # Cleanup: rollback handled by fixture
