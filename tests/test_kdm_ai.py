# tests/test_kdm_ai.py
from app.services.ai_capability_registry import get_action_types, get_handler


def test_kdm_capabilities_registered():
    import app.services.ai_assistant  # noqa: F401  (forces registration)
    types = get_action_types()
    assert "propose_kdm_request" in types
    assert "propose_cinema_server" in types
    assert callable(get_handler("propose_kdm_request"))


def test_propose_cinema_server_creates_facility_and_server():
    import app.services.ai_assistant  # noqa: F401
    from app.services.ai_capability_registry import get_handler
    from app.database import SessionLocal, create_tables
    create_tables()
    db = SessionLocal()
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
    finally:
        db.rollback()
        db.close()


def test_propose_kdm_request_creates_request():
    import app.services.ai_assistant  # noqa: F401
    from app.services.ai_capability_registry import get_handler
    from app.database import SessionLocal, create_tables
    create_tables()
    db = SessionLocal()
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
    finally:
        db.rollback()
        db.close()
