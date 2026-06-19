# tests/test_kdm_ai.py
from app.services.ai_capability_registry import get_action_types, get_handler


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


def test_propose_cinema_server_creates_facility_and_server():
    import app.services.ai_assistant  # noqa: F401
    from app.services.ai_capability_registry import get_handler
    from app.models import CinemaFacility, CinemaServer
    from app.database import SessionLocal, create_tables
    create_tables()
    db = SessionLocal()
    fac_id = None
    srv_id = None
    try:
        handler = get_handler("propose_cinema_server")
        result = handler(db, {
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
        fac_id = result["facility_id"]
        srv_id = result["server_id"]
    finally:
        # Explicit cleanup: handler commits, so rollback is a no-op; delete explicitly.
        if srv_id is not None:
            db.query(CinemaServer).filter(CinemaServer.id == srv_id).delete()
        if fac_id is not None:
            db.query(CinemaFacility).filter(CinemaFacility.id == fac_id).delete()
        db.commit()
        db.close()


def test_propose_cinema_server_invalid_kind_falls_back():
    """m2: invalid kind must be silently normalized to 'cinema'."""
    import app.services.ai_assistant  # noqa: F401
    from app.services.ai_capability_registry import get_handler
    from app.models import CinemaFacility, CinemaServer
    from app.database import SessionLocal, create_tables
    create_tables()
    db = SessionLocal()
    fac_id = None
    srv_id = None
    try:
        handler = get_handler("propose_cinema_server")
        result = handler(db, {
            "facility_name": "Test Kind Guard Cinema",
            "kind": "unknown_garbage_value",
        })
        fac_id = result["facility_id"]
        srv_id = result["server_id"]
        fac = db.query(CinemaFacility).filter(CinemaFacility.id == fac_id).first()
        assert fac is not None
        assert fac.kind == "cinema", f"Expected 'cinema', got {fac.kind!r}"
    finally:
        if srv_id is not None:
            db.query(CinemaServer).filter(CinemaServer.id == srv_id).delete()
        if fac_id is not None:
            db.query(CinemaFacility).filter(CinemaFacility.id == fac_id).delete()
        db.commit()
        db.close()


def test_propose_kdm_request_creates_request():
    import app.services.ai_assistant  # noqa: F401
    from app.services.ai_capability_registry import get_handler
    from app.models import KdmRequest
    from app.database import SessionLocal, create_tables
    create_tables()
    db = SessionLocal()
    req_id = None
    try:
        handler = get_handler("propose_kdm_request")
        result = handler(db, {
            "request_type": "kdm",
            "requested_title": "Test Film AI",
        })
        assert "kdm_request_id" in result
        assert isinstance(result["kdm_request_id"], int)
        assert result["status"] in ("received", "matched")
        assert isinstance(result["candidates"], list)
        req_id = result["kdm_request_id"]
    finally:
        # Explicit cleanup: handler commits, so rollback is a no-op; delete explicitly.
        if req_id is not None:
            db.query(KdmRequest).filter(KdmRequest.id == req_id).delete()
            db.commit()
        db.close()
