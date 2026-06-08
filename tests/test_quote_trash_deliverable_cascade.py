"""v3.5.0-alpha.172.208 — cestinare una Quote deve cestinare in cascata i
JobDeliverable spawnati dalle sue righe (altrimenti restano "orfani" nel
planning: sorgente cestinata, deliverable vivo). Il restore è simmetrico.

Bug originale: job GLO-J007 "Gomorra" aveva 8 deliverable (6 Fremantle + 2
subtitle) derivati dalle righe di una quote cestinata, rimasti vivi.
"""
from datetime import date

from app.models import models as m
from app.services.soft_delete import soft_delete_quote, restore_quote


def _seed(db, *, with_booking=False, billed=False):
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR"))
    u = m.User(tenant_id=1, email="a@b.it", full_name="A", hashed_password="x",
               role="admin")
    db.add(u)
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()
    quote = m.Quote(tenant_id=1, number="Q-2026-010-v1", title="Q",
                    issue_date=date.today(), project_id=p.id, client_id=c.id,
                    status=m.QuoteStatus.approved, currency="EUR", fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    line = m.QuoteLine(quote_id=quote.id, description="ProRes", quantity=1,
                       unit="pc", unit_price=800.0, total=800.0)
    db.add(line); db.flush()
    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=quote.id,
                code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name="ProRes",
                         quote_line_id=line.id,
                         billing_status=("billed" if billed else "not_billed"))
    db.add(d); db.flush()
    if with_booking:
        bk = m.Booking(tenant_id=1, job_id=job.id, job_deliverable_id=d.id,
                       title="bk", start=date.today(), end=date.today())
        db.add(bk); db.flush()
    return u, quote, job, d


def test_trash_quote_cascades_to_deliverables(db):
    u, quote, job, d = _seed(db)
    res = soft_delete_quote(db, quote, user=u)
    db.flush()
    assert res["deliverables_count"] == 1
    refreshed = (db.query(m.JobDeliverable)
                 .execution_options(include_deleted=True)
                 .filter(m.JobDeliverable.id == d.id).first())
    assert refreshed.deleted_at is not None  # non più orfano


def test_restore_quote_restores_deliverables(db):
    u, quote, job, d = _seed(db)
    soft_delete_quote(db, quote, user=u); db.flush()
    res = restore_quote(db, quote); db.flush()
    assert res["deliverables_count"] == 1
    refreshed = db.query(m.JobDeliverable).filter(m.JobDeliverable.id == d.id).first()
    assert refreshed is not None
    assert refreshed.deleted_at is None
    assert "[quote-trash]" not in (refreshed.notes or "")


def test_billed_deliverable_not_cascaded(db):
    """Deliverable fatturato non segue la quote nel cestino (difensivo)."""
    u, quote, job, d = _seed(db, billed=True)
    res = soft_delete_quote(db, quote, user=u); db.flush()
    assert res["deliverables_count"] == 0
    refreshed = (db.query(m.JobDeliverable)
                 .execution_options(include_deleted=True)
                 .filter(m.JobDeliverable.id == d.id).first())
    assert refreshed.deleted_at is None  # resta vivo


def test_manually_deleted_deliverable_not_restored(db):
    """Un deliverable cestinato a mano (senza tag) non viene ripristinato dal
    restore della quote."""
    u, quote, job, d = _seed(db)
    # cestino a mano PRIMA, senza tag cascade
    from app.services.clock import now_utc
    d.deleted_at = now_utc()
    db.flush()
    soft_delete_quote(db, quote, user=u); db.flush()
    restore_quote(db, quote); db.flush()
    refreshed = (db.query(m.JobDeliverable)
                 .execution_options(include_deleted=True)
                 .filter(m.JobDeliverable.id == d.id).first())
    assert refreshed.deleted_at is not None  # resta cestinato
