from app.database import SessionLocal, create_tables
from app.models import DcpCpl, KdmRequest
from app.services.kdm_match import match_request, AUTO_LINK_THRESHOLD


def _seed(db):
    db.query(DcpCpl).delete()
    db.add(DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:exact-1", source="manual",
                  content_title_text="QUEER_FTR_2K_IT"))
    db.add(DcpCpl(tenant_id=1, cpl_uuid="urn:uuid:other-2", source="manual",
                  content_title_text="DUNE_FTR_4K_EN"))
    db.commit()


def test_exact_uuid_match_is_100():
    create_tables(); db = SessionLocal()
    try:
        _seed(db)
        req = KdmRequest(tenant_id=1, request_type="kdm",
                         requested_cpl_uuid="urn:uuid:exact-1")
        out = match_request(db, req)
        assert out and out[0]["confidence"] == 100
        assert out[0]["confidence"] >= AUTO_LINK_THRESHOLD
    finally:
        db.rollback(); db.close()


def test_fuzzy_title_match_ranks():
    create_tables(); db = SessionLocal()
    try:
        _seed(db)
        req = KdmRequest(tenant_id=1, request_type="kdm",
                         requested_title="QUEER feature 2K")
        out = match_request(db, req)
        assert out and "QUEER" in out[0]["title"]
        assert 0 < out[0]["confidence"] < 100
    finally:
        db.rollback(); db.close()


def test_no_match_returns_empty():
    create_tables(); db = SessionLocal()
    try:
        _seed(db)
        req = KdmRequest(tenant_id=1, request_type="kdm",
                         requested_title="zzz nothing zzz")
        out = match_request(db, req)
        assert out == [] or out[0]["confidence"] < 40
    finally:
        db.rollback(); db.close()
