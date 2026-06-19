from app.database import SessionLocal, create_tables
from app.models import KdmRequest
import app.services.kdm_notify as kn


def test_notify_calls_inapp_and_email(monkeypatch):
    create_tables(); db = SessionLocal()
    calls = {"inapp": 0, "email": 0}
    monkeypatch.setattr(kn, "notify_permission",
                        lambda *a, **k: calls.__setitem__("inapp", calls["inapp"] + 1))
    monkeypatch.setattr(kn, "_send_email_safe",
                        lambda *a, **k: calls.__setitem__("email", calls["email"] + 1))
    try:
        req = KdmRequest(tenant_id=1, request_type="kdm", status="received",
                         requested_title="X")
        db.add(req); db.flush()
        kn.notify_new_kdm_request(db, req)
        assert calls["inapp"] == 1 and calls["email"] == 1
    finally:
        db.rollback(); db.close()
