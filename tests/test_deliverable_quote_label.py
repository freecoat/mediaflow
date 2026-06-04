"""v3.5.0-alpha.172.187 — la lista deliverable del Planning espone la
quotazione sorgente (Job.quote_id → Quote.number)."""
import asyncio
from datetime import date
from app.models import models as m
from app.routers import jobs as jobs_router


def _call(coro):
    return asyncio.run(coro)


def _seed(db):
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR"))
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-2026-008-v2", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.approved,
                    currency="EUR", fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=quote.id,
                code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name="DCP IT")
    db.add(d); db.flush()
    return quote, job, d


def test_deliverables_list_exposes_quote_number(db, monkeypatch):
    monkeypatch.setattr(jobs_router, "current_tenant_id", lambda: 1)
    quote, job, d = _seed(db)
    res = _call(jobs_router.list_deliverables_tenant_wide(db=db))
    assert res["count"] == 1
    item = res["items"][0]
    assert item["quote_id"] == quote.id
    assert item["quote_number"] == "Q-2026-008-v2"


def test_deliverables_list_quote_none_when_job_has_no_quote(db, monkeypatch):
    monkeypatch.setattr(jobs_router, "current_tenant_id", lambda: 1)
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR"))
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P2", title="P", client_id=c.id); db.add(p); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=None,
                code="J2", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name="ProRes"); db.add(d); db.flush()
    res = _call(jobs_router.list_deliverables_tenant_wide(db=db))
    item = [x for x in res["items"] if x["job_id"] == job.id][0]
    assert item["quote_id"] is None
    assert item["quote_number"] is None
