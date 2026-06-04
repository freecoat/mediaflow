"""v3.5.0-alpha.172.190 — tool readonly read_quote_lines: conteggio righe
quote per natura (lavorazione vs consegna/deliverable), per id o numero.
"""
from datetime import date
import pytest
from app.models import models as m
from app.services.ai_assistant import _h_read_quote_lines


def _seed(db, number="Q-2026-008-v4"):
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        db.add(m.Tenant(id=1, name="T", slug="t", default_currency="EUR")); db.flush()
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="GLO", title="Gomorra", client_id=c.id); db.add(p); db.flush()
    q = m.Quote(tenant_id=1, number=number, title="Q", issue_date=date.today(),
                project_id=p.id, client_id=c.id, status=m.QuoteStatus.draft,
                currency="EUR", fx_rate_to_base=1.0)
    db.add(q); db.flush()
    specs = [
        ("Dailies workflow", "day"),         # lavorazione
        ("Color grading", "day"),            # lavorazione
        ("DCP INTEROP", "pc"),               # consegna
        ("ProRes 422 HQ", "pc"),             # consegna
        ("LTO archive", "TB"),               # consegna
    ]
    for i, (desc, unit) in enumerate(specs):
        db.add(m.QuoteLine(quote_id=q.id, section="A", position=f"A.{i+1}",
                           description=desc, quantity=1.0, unit=unit, unit_price=100.0,
                           allowance=0.0, line_discount_pct=0.0, total=100.0,
                           hardcosts=0.0, sort_order=i))
    db.flush()
    return q


def test_read_quote_lines_counts_by_nature_by_number(db):
    q = _seed(db)
    res = _h_read_quote_lines(db, {"quote_number": "Q-2026-008-v4"})
    assert res["quote_number"] == "Q-2026-008-v4"
    assert res["counts"]["total"] == 5
    assert res["counts"]["lavorazioni"] == 2
    assert res["counts"]["consegne"] == 3
    natures = {ln["description"]: ln["nature"] for ln in res["lines"]}
    assert natures["DCP INTEROP"] == "consegna"
    assert natures["Dailies workflow"] == "lavorazione"


def test_read_quote_lines_by_id(db):
    q = _seed(db, number="Q-2026-009-v1")
    res = _h_read_quote_lines(db, {"quote_id": q.id})
    assert res["quote_id"] == q.id
    assert res["counts"]["consegne"] == 3


def test_read_quote_lines_not_found(db):
    with pytest.raises(ValueError):
        _h_read_quote_lines(db, {"quote_number": "Q-INESISTENTE"})


def test_read_quote_lines_requires_identifier(db):
    with pytest.raises(ValueError):
        _h_read_quote_lines(db, {})


def test_build_context_quote_overview_has_nature_counts(db, monkeypatch):
    """Il contesto deve esporre il conteggio consegne per ogni quote, così
    anche i provider legacy (no tool) possono rispondere a "quante consegne?"."""
    from app.services import ai_context
    monkeypatch.setattr(ai_context, "CURRENT_TENANT", 1)
    _seed(db, number="Q-2026-008-v4")  # 2 lavorazioni + 3 consegne
    ctx = ai_context.build_context(db)
    assert "QUOTE ESISTENTI" in ctx
    # la riga della quote deve riportare lav 2 · consegne 3
    assert "lav 2 · consegne 3" in ctx
