from datetime import date
from app.models import models as m
from app.services import currency as cur
import app.services.fx as fx


def _mk_invoice(db, currency="EUR"):
    t = db.query(m.Tenant).filter(m.Tenant.id == 1).first()
    if not t:
        t = m.Tenant(id=1, name="T", slug="t", default_currency="EUR"); db.add(t); db.flush()
    cl = db.query(m.Client).filter(m.Client.tenant_id == 1).first()
    if not cl:
        cl = m.Client(tenant_id=1, name="C"); db.add(cl); db.flush()
    inv = m.Invoice(tenant_id=1, number="F1", kind=m.InvoiceKind.regular,
                    client_id=cl.id, doc_type="TD01",
                    currency=currency, issue_date=date(2026, 5, 31), total=1000.0)
    db.add(inv); db.flush()
    return inv


def test_freeze_invoice_fx_uses_emission_date_rate(db, monkeypatch):
    inv = _mk_invoice(db, "USD")
    monkeypatch.setattr(fx, "get_fx_rate_on", lambda db, a, b, d: 0.92)
    cur.freeze_invoice_fx(db, inv, base="EUR")
    assert inv.fx_rate_to_base == 0.92
    assert inv.fx_rate_fixed_at is not None


def test_freeze_invoice_fx_base_currency_noop(db, monkeypatch):
    inv = _mk_invoice(db, "EUR")
    cur.freeze_invoice_fx(db, inv, base="EUR")
    assert inv.fx_rate_to_base == 1.0


def test_freeze_invoice_fx_422_when_no_rate(db, monkeypatch):
    import pytest
    from fastapi import HTTPException
    inv = _mk_invoice(db, "USD")
    monkeypatch.setattr(fx, "get_fx_rate_on", lambda db, a, b, d: None)
    with pytest.raises(HTTPException) as ei:
        cur.freeze_invoice_fx(db, inv, base="EUR")
    assert ei.value.status_code == 422
