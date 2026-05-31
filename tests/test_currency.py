import pytest
from app.services import currency as cur


@pytest.mark.parametrize("base,rate,expected", [
    (100.0, 1.0, 100.0),
    (920.0, 0.92, 1000.0),   # 920 EUR / 0.92 = 1000 USD
    (100.0, 0.92, 108.7),    # 100/0.92=108.695.. -> 108.70 HALF_UP
])
def test_to_display(base, rate, expected):
    assert cur.to_display(base, rate) == expected


@pytest.mark.parametrize("ccy_amt,rate,expected", [
    (1000.0, 0.92, 920.0),   # 1000 USD * 0.92 = 920 EUR base
    (100.0, 1.0, 100.0),
])
def test_to_base(ccy_amt, rate, expected):
    assert cur.to_base(ccy_amt, rate) == expected


def test_roundtrip_base_preserved():
    base = 1234.56
    disp = cur.to_display(base, 0.92)
    assert abs(cur.to_base(disp, 0.92) - base) < 0.02


def test_symbol():
    assert cur.symbol("EUR") == "€"
    assert cur.symbol("USD") == "$"
    assert cur.symbol("GBP") == "£"
    assert cur.symbol("CHF") == "CHF"
    assert cur.symbol("XXX") == "XXX"


def test_supported():
    assert cur.SUPPORTED == ["EUR", "USD", "GBP", "CHF"]


def test_format_money():
    assert cur.format_money(1234.5, "USD", 1.0) == "1.234,50 $"
    assert cur.format_money(1000.0, "USD", 0.92) == "1.086,96 $"  # 1000/0.92


def test_disclaimer_indicative_mentions_base_and_norm():
    d = cur.disclaimer("EUR", "USD", 0.92, "31/05/2026")
    assert "EUR" in d and "USD" in d and "DPR 633" in d


def test_disclaimer_emitted_mentions_emission():
    d = cur.disclaimer("EUR", "USD", 0.92, "31/05/2026", emitted=True)
    assert "emissione" in d.lower()
    assert "imponibile" in d.lower()
