"""v3.5.0-alpha.172.185 — multiselect righe quote: elimina/copia/sposta."""
import asyncio
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


def _call(coro):
    return asyncio.run(coro)


def test_transfer_copy_to_existing(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-001")
    dst, _ = _seed_quote(db, number="Q-2026-002", n_lines=0)
    res = _call(q.lines_transfer(
        quote_id=src.id,
        line_ids=f"{lines[0].id},{lines[1].id}",
        mode="copy", target="existing", target_quote_id=dst.id, db=db,
    ))
    assert res["ok"] is True
    assert res["mode"] == "copy"
    assert res["copied"] == 2
    assert res["removed"] == 0
    assert res["target_quote_id"] == dst.id
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id).count() == 2
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).count() == 2


def test_transfer_copy_preserves_capitolato_link(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-010")
    lines[0].section_label = "Sky Italia"; lines[0].delivery_item_id = 107; db.flush()
    dst, _ = _seed_quote(db, number="Q-2026-011", n_lines=0)
    _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                           mode="copy", target="existing", target_quote_id=dst.id, db=db))
    nl = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).first()
    assert nl.section_label == "Sky Italia"
    assert nl.delivery_item_id == 107


def test_transfer_target_same_as_source_400(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="copy", target="existing", target_quote_id=src.id, db=db))
    assert ei.value.status_code == 400


def test_transfer_target_not_editable_409(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-020")
    dst, _ = _seed_quote(db, number="Q-2026-021", status=m.QuoteStatus.approved, n_lines=0)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="copy", target="existing", target_quote_id=dst.id, db=db))
    assert ei.value.status_code == 409


def test_transfer_copy_assigns_progressive_numbering(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-070", n_lines=3)
    dst, _ = _seed_quote(db, number="Q-2026-071", n_lines=0)
    ids = ",".join(str(l.id) for l in lines)
    _call(q.lines_transfer(quote_id=src.id, line_ids=ids,
                           mode="copy", target="existing", target_quote_id=dst.id, db=db))
    rows = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).all()
    positions = [r.position for r in rows]
    sorts = [r.sort_order for r in rows]
    assert len(set(positions)) == 3, f"positions collidono: {positions}"
    assert len(set(sorts)) == 3, f"sort_orders collidono: {sorts}"


def test_transfer_copy_into_nonempty_quote_no_collision(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-080", n_lines=2)
    dst, dst_lines = _seed_quote(db, number="Q-2026-081", n_lines=2)
    ids = ",".join(str(l.id) for l in lines)
    _call(q.lines_transfer(quote_id=src.id, line_ids=ids,
                           mode="copy", target="existing", target_quote_id=dst.id, db=db))
    rows = db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).all()
    assert len(rows) == 4
    assert len(set(r.sort_order for r in rows)) == 4, [r.sort_order for r in rows]
    assert len(set(r.position for r in rows)) == 4, [r.position for r in rows]


def test_transfer_copy_to_new(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-030")
    res = _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                                 mode="copy", target="new", target_quote_id=None, db=db))
    assert res["copied"] == 1
    new_q = db.query(m.Quote).filter(m.Quote.id == res["target_quote_id"]).first()
    assert new_q.project_id == src.project_id
    assert new_q.client_id == src.client_id
    assert new_q.status == m.QuoteStatus.draft


def test_transfer_move_from_editable(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-040")
    dst, _ = _seed_quote(db, number="Q-2026-041", n_lines=0)
    res = _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                                 mode="move", target="existing", target_quote_id=dst.id, db=db))
    assert res["mode"] == "move"
    assert res["copied"] == 1
    assert res["removed"] == 1
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == src.id).count() == 1
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).count() == 1


def test_transfer_move_from_approved_422(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, lines = _seed_quote(db, number="Q-2026-050", status=m.QuoteStatus.approved)
    dst, _ = _seed_quote(db, number="Q-2026-051", n_lines=0)
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="move", target="existing", target_quote_id=dst.id, db=db))
    assert ei.value.status_code == 422
    # atomicità: la copia NON deve restare sulla destinazione dopo il rollback
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).count() == 0


def test_transfer_move_blocked_by_active_booking_409(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    from datetime import datetime
    src, lines = _seed_quote(db, number="Q-2026-060")
    dst, _ = _seed_quote(db, number="Q-2026-061", n_lines=0)
    job = m.Job(tenant_id=1, project_id=src.project_id, client_id=src.client_id,
                quote_id=src.id, code="JM", title="J", status=m.JobStatus.active)
    db.add(job); db.flush()
    jcl = m.JobCostLine(tenant_id=1, job_id=job.id, quote_line_id=lines[0].id,
                        description="x", quantity_quoted=1.0, unit="pc",
                        unit_price=10.0, total_quoted=10.0)
    db.add(jcl); db.flush()
    bk = m.Booking(tenant_id=1, job_cost_line_id=jcl.id, status=m.BookingStatus.confirmed,
                   start_datetime=datetime.now(), end_datetime=datetime.now())
    db.add(bk); db.flush()
    with pytest.raises(HTTPException) as ei:
        _call(q.lines_transfer(quote_id=src.id, line_ids=str(lines[0].id),
                               mode="move", target="existing", target_quote_id=dst.id, db=db))
    assert ei.value.status_code == 409
    # atomicità: il rollback del 409 deve annullare anche la copia sulla destinazione
    assert db.query(m.QuoteLine).filter(m.QuoteLine.quote_id == dst.id).count() == 0


def test_transfer_targets_lists_editable_excludes_self(db, monkeypatch):
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    src, _ = _seed_quote(db, number="Q-2026-100", n_lines=0)
    d1, _ = _seed_quote(db, number="Q-2026-101", n_lines=0)
    appr, _ = _seed_quote(db, number="Q-2026-102", status=m.QuoteStatus.approved, n_lines=0)
    out = _call(q.transfer_targets(exclude=src.id, db=db))
    ids = {r["id"] for r in out}
    assert d1.id in ids          # bozza inclusa
    assert src.id not in ids     # self escluso
    assert appr.id not in ids    # approvata esclusa
    assert all(set(r) >= {"id", "number", "title", "project_name", "client_name"} for r in out)
