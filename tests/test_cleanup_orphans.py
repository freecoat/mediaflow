from datetime import date, datetime
from app.models import models as m
from scripts.cleanup_orphan_deliverables import cleanup_orphans


def _seed_job(db):
    if not db.query(m.Tenant).filter(m.Tenant.id == 1).first():
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-1", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.approved,
                    currency="EUR", fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=quote.id,
                code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    return p, quote, job


def _mk_del(db, job, **kw):
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name=kw.get("name", "DCP"),
                         quote_line_id=kw.get("quote_line_id"),
                         quantity_planned=1.0, quantity_delivered=kw.get("qd", 0.0),
                         billing_status=kw.get("bs", m.DeliverableBillingStatus.not_billed))
    db.add(d); db.flush()
    return d


def test_cleanup_removes_clean_null_orphans(db, monkeypatch):
    import app.routers.quotes as q
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    # 3 orfani NULL puliti
    for i in range(3):
        _mk_del(db, job, name=f"orf{i}", quote_line_id=None)
    # 1 deliverable LINKATO (non orfano) → non deve essere toccato
    _mk_del(db, job, name="linked", quote_line_id=999)
    res = cleanup_orphans(db, job_id=job.id, apply=True)
    assert res["removed"] == 3
    assert res["kept_locked"] == 0
    # i 3 orfani hanno deleted_at; il linkato no
    nulls = db.query(m.JobDeliverable).filter(
        m.JobDeliverable.job_id == job.id,
        m.JobDeliverable.quote_line_id.is_(None)).all()
    assert all(d.deleted_at is not None for d in nulls)
    linked = db.query(m.JobDeliverable).filter(m.JobDeliverable.quote_line_id == 999).first()
    assert linked.deleted_at is None


def test_cleanup_keeps_committed_orphan(db, monkeypatch):
    import app.routers.quotes as q
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    clean = _mk_del(db, job, name="clean", quote_line_id=None)
    billed = _mk_del(db, job, name="billed", quote_line_id=None, bs=m.DeliverableBillingStatus.billed)
    res = cleanup_orphans(db, job_id=job.id, apply=True)
    assert res["removed"] == 1
    assert res["kept_locked"] == 1
    db.refresh(clean); db.refresh(billed)
    assert clean.deleted_at is not None
    assert billed.deleted_at is None


def test_cleanup_dry_run_no_mutation(db, monkeypatch):
    import app.routers.quotes as q
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    _mk_del(db, job, quote_line_id=None)
    res = cleanup_orphans(db, job_id=job.id, apply=False)
    assert res["candidates"] == 1
    assert res["removed"] == 0  # dry-run
    d = db.query(m.JobDeliverable).filter(m.JobDeliverable.job_id == job.id).first()
    assert d.deleted_at is None
