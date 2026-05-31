"""Tests per il blocco valuta quote — Task 4.

Verifica _currency_block_for_quote:
- valuta base (EUR==EUR) → rate 1.0, disclaimer None
- valuta estera con tasso disponibile → rate live + disclaimer con "DPR 633"
"""
import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.models import models as m
from app.routers import quotes as q


def _mk_quote(db, currency="EUR"):
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        t = m.Tenant(id=1, name="T", slug="t", default_currency="EUR"); db.add(t)
    c = m.Client(tenant_id=1, name="C"); db.add(c); db.flush()
    p = m.Project(tenant_id=1, code="P1", title="P", client_id=c.id); db.add(p); db.flush()
    from datetime import date
    quote = m.Quote(tenant_id=1, number="Q-1", title="Test Quote",
                    issue_date=date.today(),
                    project_id=p.id, client_id=c.id,
                    currency=currency, fx_rate_to_base=1.0)
    db.add(quote); db.flush()
    return quote


def test_currency_block_base_currency(db, monkeypatch):
    quote = _mk_quote(db, currency="EUR")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    block = q._currency_block_for_quote(db, quote)
    assert block["currency"] == "EUR"
    assert block["base_currency"] == "EUR"
    assert block["live_rate"] == 1.0
    assert block["disclaimer"] is None


def test_currency_block_foreign_has_rate_and_disclaimer(db, monkeypatch):
    quote = _mk_quote(db, currency="USD")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    monkeypatch.setattr("app.services.fx.get_fx_rate", lambda db, a, b: 0.92)
    block = q._currency_block_for_quote(db, quote)
    assert block["currency"] == "USD"
    assert block["live_rate"] == 0.92
    assert block["disclaimer"] and "DPR 633" in block["disclaimer"]


def test_line_price_entered_in_currency_stored_in_base(db, monkeypatch):
    quote = _mk_quote(db, currency="USD")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    monkeypatch.setattr("app.services.fx.get_fx_rate", lambda db, a, b: 0.92)
    # input 1000 USD -> base = 1000*0.92 = 920 EUR
    assert q._line_price_to_base(db, quote, entered_price=1000.0, from_price_item=False) == 920.0


def test_line_price_from_listino_is_base_unchanged(db, monkeypatch):
    quote = _mk_quote(db, currency="USD")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    monkeypatch.setattr("app.services.fx.get_fx_rate", lambda db, a, b: 0.92)
    assert q._line_price_to_base(db, quote, entered_price=850.0, from_price_item=True) == 850.0


def test_line_price_base_currency_quote_unchanged(db, monkeypatch):
    quote = _mk_quote(db, currency="EUR")
    monkeypatch.setattr(q, "current_tenant_id", lambda: 1)
    assert q._line_price_to_base(db, quote, entered_price=500.0, from_price_item=False) == 500.0
