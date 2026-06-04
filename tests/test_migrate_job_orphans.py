"""Task 1 orphan-deliverables fix (v3.5.0-alpha.172.192).

Copre:
  - helper `_deliverable_safe_to_remove` (mirror guardia `_respawn_line_artifacts`):
    vergine → True; delivered/billed/booking-linkato → False.
  - flusso reale `migrate_job`: una riga V_old droppata in V_new → il suo
    deliverable VERGINE viene soft-deleted (deleted_at set), NON lasciato a
    quote_line_id=NULL (root cause accumulo orfani). La riga sopravvissuta
    viene re-bindata. Un deliverable con impegno a valle resta tracciato.
"""
import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.models import models as m
from app.routers import quotes as q


# ── seed helpers ──────────────────────────────────────────────────────
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


def _mk_deliverable(db, job, **kw):
    d = m.JobDeliverable(tenant_id=1, job_id=job.id, name=kw.get("name", "DCP"),
                         quote_line_id=kw.get("quote_line_id"),
                         quantity_planned=1.0, quantity_delivered=kw.get("qd", 0.0),
                         billing_status=kw.get("bs", m.DeliverableBillingStatus.not_billed),
                         confirmed_at=kw.get("confirmed_at"))
    db.add(d); db.flush()
    return d


def _mk_booking_link(db, job, d):
    """Crea un Booking minimale + BookingDeliverable che lo lega al deliverable."""
    now = datetime(2026, 6, 4, 9, 0, 0)
    b = m.Booking(tenant_id=1, job_id=job.id,
                  start_datetime=now, end_datetime=now + timedelta(hours=8))
    db.add(b); db.flush()
    bd = m.BookingDeliverable(booking_id=b.id, job_deliverable_id=d.id)
    db.add(bd); db.flush()
    return b, bd


# ── helper unit tests ─────────────────────────────────────────────────
def test_safe_to_remove_clean(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job)
    assert q._deliverable_safe_to_remove(db, d) is True


def test_safe_to_remove_blocked_delivered(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job, qd=2.0)
    assert q._deliverable_safe_to_remove(db, d) is False


def test_safe_to_remove_blocked_billed(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job, bs=m.DeliverableBillingStatus.billed)
    assert q._deliverable_safe_to_remove(db, d) is False


def test_safe_to_remove_blocked_confirmed(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job, confirmed_at=datetime(2026, 6, 4, 10, 0, 0))
    assert q._deliverable_safe_to_remove(db, d) is False


def test_safe_to_remove_blocked_booking(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    p, quote, job = _seed_job(db)
    d = _mk_deliverable(db, job)
    _mk_booking_link(db, job, d)
    assert q._deliverable_safe_to_remove(db, d) is False


# ── integration test su migrate_job reale ─────────────────────────────
def _fake_request(user):
    return SimpleNamespace(state=SimpleNamespace(current_user=user))


def _seed_versioned(db):
    """V_old (approved) con job + 2 deliverable (pc), V_new (draft) con SOLA
    1 riga che eredita parent_line_id dalla prima riga V_old. La seconda riga
    V_old è 'droppata'."""
    if not db.query(m.Tenant).filter(m.Tenant.id == 1).first():
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()

    v_old = m.Quote(tenant_id=1, number="Q-OLD", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.approved,
                    currency="EUR", fx_rate_to_base=1.0, version=1)
    db.add(v_old); db.flush()
    l1 = m.QuoteLine(quote_id=v_old.id, description="DCP A", quantity=1.0,
                     unit="pc", unit_price=100.0, total=100.0)
    l2 = m.QuoteLine(quote_id=v_old.id, description="DCP B (droppata)", quantity=1.0,
                     unit="pc", unit_price=200.0, total=200.0)
    db.add_all([l1, l2]); db.flush()

    job = m.Job(tenant_id=1, project_id=p.id, client_id=c.id, quote_id=v_old.id,
                code="J1", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    d1 = m.JobDeliverable(tenant_id=1, job_id=job.id, name="DCP A",
                          quote_line_id=l1.id, unit="pc", unit_price=100.0,
                          quantity_planned=1.0, quantity_delivered=0.0,
                          billing_status=m.DeliverableBillingStatus.not_billed)
    d2 = m.JobDeliverable(tenant_id=1, job_id=job.id, name="DCP B (droppata)",
                          quote_line_id=l2.id, unit="pc", unit_price=200.0,
                          quantity_planned=1.0, quantity_delivered=0.0,
                          billing_status=m.DeliverableBillingStatus.not_billed)
    db.add_all([d1, d2]); db.flush()

    # V_new: draft, parent=v_old, contiene SOLO la riga erede di l1.
    v_new = m.Quote(tenant_id=1, number="Q-NEW", title="Q", issue_date=date.today(),
                    project_id=p.id, client_id=c.id, status=m.QuoteStatus.draft,
                    currency="EUR", fx_rate_to_base=1.0, version=2,
                    parent_quote_id=v_old.id)
    db.add(v_new); db.flush()
    nl1 = m.QuoteLine(quote_id=v_new.id, description="DCP A v2", quantity=1.0,
                      unit="pc", unit_price=100.0, total=100.0, parent_line_id=l1.id)
    db.add(nl1); db.flush()
    return p, v_old, v_new, job, d1, d2


def test_migrate_job_drops_orphan_deliverable(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    # bypassa RBAC: utente fittizio + permesso sempre vero
    import app.services.rbac as rbac
    monkeypatch.setattr(rbac, "has_permission", lambda user, perm: True)
    user = SimpleNamespace(id=1)

    p, v_old, v_new, job, d1, d2 = _seed_versioned(db)

    res = asyncio.run(q.migrate_job(
        quote_id=v_new.id, request=_fake_request(user),
        orphan_strategy="keep_as_extra", db=db,
    ))

    db.refresh(d1); db.refresh(d2)
    # d1 (riga sopravvissuta) ri-bindata alla nuova riga
    assert d1.deleted_at is None
    assert d1.quote_line_id is not None
    assert d1.quote_line_id != d2.quote_line_id  # punta alla riga V_new
    # d2 (riga droppata) soft-deleted, NON lasciato a quote_line_id=NULL
    assert d2.deleted_at is not None
    # counters
    assert res["deliverables_rebound"] == 1
    assert res["deliverables_orphaned"] == 1
    assert res["deliverables_kept_locked"] == 0


def test_migrate_job_keeps_committed_orphan(db, monkeypatch):
    """Deliverable droppato MA con booking link → resta tracciato (no delete)."""
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    import app.services.rbac as rbac
    monkeypatch.setattr(rbac, "has_permission", lambda user, perm: True)
    user = SimpleNamespace(id=1)

    p, v_old, v_new, job, d1, d2 = _seed_versioned(db)
    _mk_booking_link(db, job, d2)  # impegno a valle su riga droppata

    res = asyncio.run(q.migrate_job(
        quote_id=v_new.id, request=_fake_request(user),
        orphan_strategy="keep_as_extra", db=db,
    ))

    db.refresh(d2)
    assert d2.deleted_at is None              # non cancellato
    assert res["deliverables_kept_locked"] == 1
    assert res["deliverables_orphaned"] == 0
