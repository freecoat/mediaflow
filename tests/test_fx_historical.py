from datetime import date
import app.services.fx as fx


def test_get_fx_rate_on_same_currency(db):
    assert fx.get_fx_rate_on(db, "EUR", "EUR", date(2026, 5, 31)) == 1.0


def test_get_fx_rate_on_uses_dated_endpoint(db, monkeypatch):
    captured = {}
    def fake_fetch_on(from_ccy, to_ccy, d):
        captured["url_date"] = d
        return 0.92
    monkeypatch.setattr(fx, "_fetch_frankfurter_on", fake_fetch_on)
    r = fx.get_fx_rate_on(db, "USD", "EUR", date(2026, 5, 31))
    assert r == 0.92
    assert captured["url_date"] == date(2026, 5, 31)


def test_get_fx_rate_on_none_when_provider_fails(db, monkeypatch):
    monkeypatch.setattr(fx, "_fetch_frankfurter_on", lambda a, b, d: None)
    assert fx.get_fx_rate_on(db, "USD", "EUR", date(2026, 5, 31)) is None
