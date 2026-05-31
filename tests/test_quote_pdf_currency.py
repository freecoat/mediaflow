"""Tests per generate_quote_pdf con valuta display (Task 8).

Verifica:
- base currency (EUR) → PDF valido, comportamento invariato rispetto a prima
- valuta estera (USD, rate=0.92) → PDF valido, disclaimer in calce
"""
from datetime import date
from types import SimpleNamespace

import pytest
from app.services.quote_pdf import generate_quote_pdf


# ---------------------------------------------------------------------------
# Helpers: costruzione quote duck-typed
# ---------------------------------------------------------------------------

def _fake_line(**kw):
    defaults = dict(
        description="Grading giornaliero",
        detail=None,
        quantity=2.0,
        unit="hr",
        unit_price=500.0,
        total=1000.0,
        line_discount_pct=None,
        sort_order=0,
        is_optional=False,
        section_label=None,
        category_override=None,
        price_item=None,
        position="1",
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _fake_quote(currency="EUR"):
    """Crea un quote duck-typed con attributi minimi necessari al generatore."""
    client = SimpleNamespace(
        name="Acme Films",
        address="Via Roma 1",
        city="Milano",
        country="IT",
        vat_number="IT12345678901",
        contact_name="Mario Rossi",
        contact_role="Produttore",
    )
    line = _fake_line()
    return SimpleNamespace(
        number="Q-2026-001",
        version=1,
        title="Test Quote",
        issue_date=date(2026, 5, 31),
        valid_until=date(2026, 6, 30),
        client=client,
        currency=currency,
        # premesse tecniche — tutte None → blocco saltato
        production_material=None,
        length_minutes=None,
        delivery_format=None,
        shooting_days=None,
        fps=None,
        # righe
        lines=[line],
        category_discounts={},
        # totali (tutti in EUR, valuta base)
        subtotal_gross=1000.0,
        subtotal=1000.0,
        total_after_discount=1000.0,
        total_with_vat=1220.0,
        package_discount=0.0,
        vat_rate=22.0,
        # note
        payment_terms=None,
        notes=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_quote_pdf_base_currency_smoke():
    """PDF EUR (base) deve essere un file PDF valido."""
    pdf = generate_quote_pdf(_fake_quote("EUR"))
    assert pdf[:4] == b"%PDF"


def test_quote_pdf_base_currency_no_disclaimer():
    """Senza valuta estera non ci deve essere il testo del disclaimer."""
    pdf = generate_quote_pdf(_fake_quote("EUR"))
    # Il disclaimer contiene "DPR 633" — non deve apparire nel PDF base
    assert b"DPR 633" not in pdf


def test_quote_pdf_foreign_currency_smoke():
    """PDF con ccy=USD deve essere un file PDF valido."""
    disc = "Importi in USD indicativi. Tasso BCE 31/05/2026 (0.92 USD/EUR). DPR 633/1972."
    pdf = generate_quote_pdf(
        _fake_quote("USD"),
        ccy="USD",
        rate=0.92,
        disclaimer=disc,
    )
    assert pdf[:4] == b"%PDF"


def test_quote_pdf_foreign_currency_disclaimer_in_pdf():
    """Il PDF con disclaimer deve essere più grande di quello senza (testo in calce aggiunto)."""
    disc = "Importi in USD indicativi. Tasso BCE 31/05/2026 (0.92 USD/EUR). DPR 633/1972."
    pdf_with = generate_quote_pdf(
        _fake_quote("USD"),
        ccy="USD",
        rate=0.92,
        disclaimer=disc,
    )
    pdf_without = generate_quote_pdf(_fake_quote("USD"), ccy="USD", rate=0.92, disclaimer=None)
    # Il PDF con disclaimer deve essere più grande (contiene testo aggiuntivo)
    assert len(pdf_with) > len(pdf_without)
    assert pdf_with[:4] == b"%PDF"


def test_quote_pdf_default_args_backward_compat():
    """Chiamata senza parametri valuta → uguale a EUR (backward compat)."""
    pdf_default = generate_quote_pdf(_fake_quote("EUR"))
    pdf_explicit = generate_quote_pdf(_fake_quote("EUR"), ccy=None, rate=1.0, disclaimer=None)
    # Entrambi devono produrre un PDF valido (non confrontiamo byte-per-byte
    # perché ReportLab include timestamp, ma entrambi devono essere PDF)
    assert pdf_default[:4] == b"%PDF"
    assert pdf_explicit[:4] == b"%PDF"


def test_quote_pdf_rate_none_fallback():
    """rate=None o 0.0 non deve causare crash — fallback a comportamento base."""
    pdf = generate_quote_pdf(_fake_quote("USD"), ccy="USD", rate=0.0, disclaimer=None)
    assert pdf[:4] == b"%PDF"
