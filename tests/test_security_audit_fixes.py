"""Test di regressione per i fix dell'audit multi-agent (30 mag 2026).

Copre le aree che prima dell'audit NON avevano test automatici:
- tenant isolation (tenant_guard) — cross-tenant 404
- UNIQUE composito scoped al tenant (Project/Job/Quote)
- finance: Decimal/HALF_UP su invoice acconto, fx rounding
- italian_tax: validator SDI 6/7 char
- quotes: price_list None non più silenziato a €0 (warning)

v3.5.0-alpha.172.142.
"""
import pytest
from datetime import date
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

from app.models import models as m
from app.services.money import to_decimal, money_round, money_to_float
from app.services.italian_tax import validate_sdi_code
from app.services import tenant_guard
from app.routers.quotes import _resolve_item_unit_price, PriceLevel


# ── italian_tax: SDI 6/7 char ────────────────────────────────────────
@pytest.mark.parametrize("code,expected", [
    ("ABC1234", True),    # 7 alfanum privati
    ("0000000", True),    # consumer/PEC
    ("XXXXXXX", True),    # estero 7
    ("999999", True),     # PA 6 (era il solo special-case)
    ("UF0001", True),     # iPA office 6
    ("12345", False),     # 5 char
    ("ABCDEFGH", False),  # 8 char
    ("AB!234", False),    # non-alnum
    ("", False),
    (None, False),
])
def test_validate_sdi_code_6_or_7(code, expected):
    assert validate_sdi_code(code) is expected


# ── finance: Decimal/HALF_UP coerente ────────────────────────────────
def test_money_round_half_up_not_bankers():
    # float round() usa banker's (HALF_EVEN): round(2.675,2)==2.67.
    # money_round (HALF_UP) deve dare 2.68.
    assert money_round(to_decimal("2.675")) == Decimal("2.68")
    assert money_round(to_decimal("2.665")) == Decimal("2.67")


def test_advance_invoice_decimal_consistency():
    # Replica il calcolo dell'invoice acconto (finance.py): sub + vat == total
    amount = 1000000.01
    vat_rate = 22
    sub = money_round(to_decimal(amount))
    vat = money_round(sub * to_decimal(vat_rate) / to_decimal(100))
    total = money_round(sub + vat)
    assert money_to_float(sub) == 1000000.01
    assert money_to_float(total) == money_to_float(sub) + money_to_float(vat)
    # invariante Σ(round) == round(Σ)
    assert total == money_round(sub + vat)


# ── fx: convert arrotonda a 2 decimali ───────────────────────────────
def test_fx_convert_rounds(db, monkeypatch):
    import app.services.fx as fx
    monkeypatch.setattr(fx, "get_fx_rate", lambda db, a, b: 1.08523)
    # 1000.00 * 1.08523 = 1085.23 (arrotondato), non 1085.23000...
    out = fx.convert(1000.00, "USD", "EUR", db)
    assert out == 1085.23
    # verifica che sia davvero arrotondato a 2 cifre
    assert round(out, 2) == out


def test_fx_convert_none_when_no_rate(db, monkeypatch):
    import app.services.fx as fx
    monkeypatch.setattr(fx, "get_fx_rate", lambda db, a, b: None)
    assert fx.convert(100.0, "USD", "EUR", db) is None


# ── quotes: price_list None → €0 ma con warning (non silenzioso) ──────
def _mk_price_item(db, *, price_list):
    cat = m.PriceCategory(name="TestCat", tenant_id=1)
    db.add(cat); db.flush()
    it = m.PriceItem(category_id=cat.id, name="Voce test", unit="pc",
                     price_list=price_list, tenant_id=1)
    db.add(it); db.flush()
    return it


def test_resolve_unit_price_present(db):
    it = _mk_price_item(db, price_list=120.0)
    assert _resolve_item_unit_price(it, PriceLevel.list_price) == 120.0


def test_resolve_unit_price_none_warns(db, caplog):
    it = _mk_price_item(db, price_list=None)
    with caplog.at_level("WARNING"):
        val = _resolve_item_unit_price(it, PriceLevel.list_price)
    assert val == 0.0
    assert any("senza prezzo" in r.message or "MANCANTE" in r.message
               for r in caplog.records), "atteso warning sul prezzo mancante"


# ── tenant_guard: cross-tenant 404 ───────────────────────────────────
def test_fetch_or_404_cross_tenant_blocked(db):
    # current_tenant_id() == 1 (default test). Record di tenant 2 → 404.
    c1 = m.Client(name="C1", tenant_id=1)
    c2 = m.Client(name="C2", tenant_id=2)
    db.add_all([c1, c2]); db.commit()
    # tenant 1 → ok
    got = tenant_guard.fetch_or_404(db, m.Client, c1.id)
    assert got.id == c1.id
    # tenant 2 → 404 (no enumeration leak)
    with pytest.raises(HTTPException) as ei:
        tenant_guard.fetch_or_404(db, m.Client, c2.id)
    assert ei.value.status_code == 404


def test_scoped_filters_by_tenant(db):
    db.add_all([m.Client(name="A", tenant_id=1),
                m.Client(name="B", tenant_id=2),
                m.Client(name="C", tenant_id=1)])
    db.commit()
    rows = tenant_guard.scoped(db.query(m.Client), m.Client).all()
    assert {r.tenant_id for r in rows} == {1}
    assert len(rows) == 2


# ── modelli: UNIQUE composito (tenant_id, code|number) ───────────────
def test_project_code_unique_per_tenant_not_global(db):
    # stesso code in tenant diversi = OK (era vietato dal vincolo globale)
    db.add(m.Project(tenant_id=1, code="PRJ-001", title="t", client_id=1))
    db.add(m.Project(tenant_id=2, code="PRJ-001", title="t", client_id=1))
    db.commit()  # no error
    # stesso code nello STESSO tenant = IntegrityError
    db.add(m.Project(tenant_id=1, code="PRJ-001", title="dup", client_id=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_job_code_unique_per_tenant(db):
    db.add(m.Job(tenant_id=1, code="JOB-1", title="t", project_id=1, client_id=1))
    db.add(m.Job(tenant_id=2, code="JOB-1", title="t", project_id=1, client_id=1))
    db.commit()
    db.add(m.Job(tenant_id=1, code="JOB-1", title="dup", project_id=1, client_id=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_quote_number_unique_per_tenant(db):
    db.add(m.Quote(tenant_id=1, number="Q-1", title="t", project_id=1, client_id=1, issue_date=date.today()))
    db.add(m.Quote(tenant_id=2, number="Q-1", title="t", project_id=1, client_id=1, issue_date=date.today()))
    db.commit()
    db.add(m.Quote(tenant_id=1, number="Q-1", title="dup", project_id=1, client_id=1, issue_date=date.today()))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
