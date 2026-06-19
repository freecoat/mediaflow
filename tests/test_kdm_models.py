# tests/test_kdm_models.py
from app.database import SessionLocal, create_tables
from app.models import (
    DcpCpl, CinemaFacility, CinemaServer, KdmRequest, KdmRequestEvent,
)


def test_kdm_models_roundtrip():
    create_tables()
    db = SessionLocal()
    try:
        fac = CinemaFacility(tenant_id=1, name="UCI Bicocca", kind="cinema")
        db.add(fac); db.flush()
        srv = CinemaServer(tenant_id=1, facility_id=fac.id,
                           manufacturer="dolby", serial="IMS3000-123")
        db.add(srv); db.flush()
        req = KdmRequest(tenant_id=1, request_type="kdm", client_id=None,
                         status="received", target_facility_id=fac.id,
                         target_server_id=srv.id)
        db.add(req); db.flush()
        ev = KdmRequestEvent(kdm_request_id=req.id, event_type="created",
                             payload_json={})
        db.add(ev); db.flush()
        cpl = DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:abc", source="manual",
                     content_title_text="QUEER_FTR")
        db.add(cpl); db.commit()
        assert req.id and srv.facility_id == fac.id and cpl.cpl_uuid == "urn:uuid:abc"
    finally:
        db.rollback(); db.close()
