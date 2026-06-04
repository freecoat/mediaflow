from datetime import date
import pytest
from app.models import models as m
from app.services.ai_assistant import _h_read_job_deliverables


def _seed(db):
    if not db.query(m.Tenant).filter(m.Tenant.id == 1).first():
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="GLO", title="Gomorra", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-2026-008-v5", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.approved,
                    currency="EUR", fx_rate_to_base=1.0); db.add(quote); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=quote.id,
                code="GLO-J007", title="J", status=m.JobStatus.active); db.add(job); db.flush()
    ql = m.QuoteLine(quote_id=quote.id, section="A", position="A.1", description="DCP",
                     quantity=1.0, unit="pc", unit_price=100.0, allowance=0.0,
                     line_discount_pct=0.0, total=100.0, hardcosts=0.0, sort_order=0,
                     section_label="Sky Italia"); db.add(ql); db.flush()
    for i in range(2):
        db.add(m.JobDeliverable(tenant_id=1, job_id=job.id, name="DCP - CS", quote_line_id=ql.id,
                                unit="pc", quantity_planned=1.0))
    db.flush()
    return p, job


def test_read_job_deliverables_by_job_id(db):
    p, job = _seed(db)
    res = _h_read_job_deliverables(db, {"job_id": job.id})
    assert res["count"] == 2
    assert res["items"][0]["name"] == "DCP - CS"
    assert res["items"][0]["section_label"] == "Sky Italia"
    assert res["items"][0]["unit"] == "pc"
    assert "id" in res["items"][0]


def test_read_job_deliverables_by_project_code(db):
    p, job = _seed(db)
    res = _h_read_job_deliverables(db, {"project_code": "GLO"})
    assert res["count"] == 2


def test_read_job_deliverables_not_found(db):
    with pytest.raises(ValueError):
        _h_read_job_deliverables(db, {"job_id": 999999})


from app.services.ai_assistant import _h_propose_rename_deliverables


def test_rename_deliverables_applies(db):
    p, job = _seed(db)
    rows = db.query(m.JobDeliverable).filter(m.JobDeliverable.job_id == job.id).order_by(m.JobDeliverable.id).all()
    renames = [{"deliverable_id": rows[0].id, "new_name": "DCP - CS - ep. 101"},
               {"deliverable_id": rows[1].id, "new_name": "DCP - CS - ep. 102"}]
    res = _h_propose_rename_deliverables(db, {"renames": renames})
    assert res["renamed"] == 2
    db.refresh(rows[0]); db.refresh(rows[1])
    assert rows[0].name == "DCP - CS - ep. 101"
    assert rows[1].name == "DCP - CS - ep. 102"


def test_rename_deliverables_skips_unknown(db):
    p, job = _seed(db)
    res = _h_propose_rename_deliverables(db, {"renames": [{"deliverable_id": 999999, "new_name": "X"}]})
    assert res["renamed"] == 0
    assert res["skipped"] == 1


def test_rename_deliverables_empty_raises(db):
    with pytest.raises(ValueError):
        _h_propose_rename_deliverables(db, {"renames": []})
