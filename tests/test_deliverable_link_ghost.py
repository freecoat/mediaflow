from datetime import date

from app.models import models as m
from app.services.deliverable_ghost_link import link_deliverable_to_ghost


def _seed(db):
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
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name="DCP extra", quote_line_id=None,
                         unit="pc", unit_price=100.0, quantity_planned=1.0)
    db.add(d); db.flush()
    return p, job, d


def test_link_creates_phantom_and_links(db, monkeypatch):
    import app.services.deliverable_ghost_link as g
    monkeypatch.setattr(g, "current_tenant_id", lambda: 1)
    p, job, d = _seed(db)
    res = link_deliverable_to_ghost(db, d.id)
    assert res["ok"] is True
    db.refresh(d)
    assert d.quote_line_id is not None
    ql = db.query(m.QuoteLine).filter(m.QuoteLine.id == d.quote_line_id).first()
    phantom = db.query(m.Quote).filter(m.Quote.id == ql.quote_id).first()
    assert phantom.is_phantom is True
    assert phantom.project_id == p.id


def test_link_idempotent_reuses_phantom(db, monkeypatch):
    import app.services.deliverable_ghost_link as g
    monkeypatch.setattr(g, "current_tenant_id", lambda: 1)
    p, job, d = _seed(db)
    d2 = m.JobDeliverable(tenant_id=1, job_id=job.id, name="ProRes extra", quote_line_id=None,
                          unit="pc", unit_price=50.0, quantity_planned=1.0)
    db.add(d2); db.flush()
    r1 = link_deliverable_to_ghost(db, d.id)
    r2 = link_deliverable_to_ghost(db, d2.id)
    # stessa phantom riusata
    assert r1["quote_id"] == r2["quote_id"]


def test_link_already_linked_noop(db, monkeypatch):
    import app.services.deliverable_ghost_link as g
    monkeypatch.setattr(g, "current_tenant_id", lambda: 1)
    p, job, d = _seed(db)
    d.quote_line_id = 12345  # già linkato
    db.flush()
    res = link_deliverable_to_ghost(db, d.id)
    assert res["quote_line_id"] == 12345  # invariato
    assert res.get("already_linked") is True
