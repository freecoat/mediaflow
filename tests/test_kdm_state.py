import pytest
from app.database import SessionLocal, create_tables
from app.models import KdmRequest, KdmRequestEvent
from app.services.kdm_state import transition, ALLOWED_TRANSITIONS


def test_legal_transition_stamps_and_logs():
    create_tables(); db = SessionLocal()
    try:
        req = KdmRequest(tenant_id=1, request_type="kdm", status="generated")
        db.add(req); db.flush()
        transition(db, req, "delivered", user_id=1)
        assert req.status == "delivered" and req.delivered_at is not None
        evs = db.query(KdmRequestEvent).filter_by(kdm_request_id=req.id).all()
        assert any(e.event_type == "transition" for e in evs)
    finally:
        db.rollback(); db.close()


def test_illegal_transition_raises():
    create_tables(); db = SessionLocal()
    try:
        req = KdmRequest(tenant_id=1, request_type="kdm", status="received")
        db.add(req); db.flush()
        with pytest.raises(ValueError):
            transition(db, req, "confirmed")
    finally:
        db.rollback(); db.close()


def test_transition_table_shape():
    assert "matched" in ALLOWED_TRANSITIONS["received"]
    assert "rejected" in ALLOWED_TRANSITIONS["received"]
