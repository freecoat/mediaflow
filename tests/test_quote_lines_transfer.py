"""v3.5.0-alpha.172.185 — multiselect righe quote: elimina/copia/sposta."""
from datetime import date, datetime
import pytest
from fastapi import HTTPException
from app.models import models as m
from app.routers import quotes as q


def _seed_quote(db, tenant=1, status=m.QuoteStatus.draft, number="Q-2026-001", n_lines=2):
    t = db.query(m.Tenant).filter(m.Tenant.id == tenant).first()
    if not t:
        t = m.Tenant(id=tenant, name="T", slug=f"t{tenant}", default_currency="EUR"); db.add(t)
    c = m.Client(tenant_id=tenant, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=tenant, code=f"P{number}", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=tenant, number=number, title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=status,
                    currency="EUR", fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    lines = []
    for i in range(n_lines):
        ln = m.QuoteLine(quote_id=quote.id, section="A", position=f"A.{i+1}",
                         description=f"L{i}", quantity=1.0, unit="pc", unit_price=100.0,
                         allowance=0.0, line_discount_pct=0.0, total=100.0, hardcosts=0.0,
                         sort_order=i)
        db.add(ln); lines.append(ln)
    db.flush()
    return quote, lines


def test_remove_quote_lines_deletes_clean(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    quote, lines = _seed_quote(db)
    ids = [lines[0].id]
    removed, details = q._remove_quote_lines(db, quote, ids)
    assert removed == 1
    remaining = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == quote.id).count()
    assert remaining == 1


def test_remove_quote_lines_blocks_on_active_booking(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    quote, lines = _seed_quote(db)
    # crea job + JCL + booking attivo collegati alla riga 0
    job = m.Job(tenant_id=1, project_id=quote.project_id, client_id=quote.client_id,
                quote_id=quote.id, code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    jcl = m.JobCostLine(tenant_id=1, job_id=job.id, quote_line_id=lines[0].id,
                        description="x", quantity_quoted=1.0, unit="pc",
                        unit_price=10.0, total_quoted=10.0)
    db.add(jcl); db.flush()
    bk = m.Booking(tenant_id=1, job_cost_line_id=jcl.id, status=m.BookingStatus.confirmed,
                   start_datetime=datetime.now(), end_datetime=datetime.now())
    db.add(bk); db.flush()
    with pytest.raises(HTTPException) as ei:
        q._remove_quote_lines(db, quote, [lines[0].id])
    assert ei.value.status_code == 409
