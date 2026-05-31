"""Servizio FX rate — v3.5.0-alpha.137.

Provider primario: Frankfurter (api.frankfurter.app), BCE-based, free, no API key.
Endpoint: https://api.frankfurter.app/latest?from=<FROM>&to=<TO>

Cache locale via FXRate ORM. TTL default 1h. Refresh on-demand.
Tutte le funzioni sono fail-soft: errori network ritornano None senza alzare.

API principali:
- get_fx_rate(db, from_ccy, to_ccy, max_age_minutes=60) → float | None
- refresh_fx_rate(db, from_ccy, to_ccy) → float | None (forza refresh)
- convert(amount, from_ccy, to_ccy, db) → float | None

Convenzione: rate è "quanti to_ccy per 1 from_ccy". Es. rate(USD,EUR)=0.92
significa 1 USD = 0.92 EUR.
"""
from app.services.clock import now_utc
from datetime import datetime, timedelta
from typing import Optional
import urllib.request
import urllib.error
import json
import logging

from sqlalchemy.orm import Session
from app.models import FXRate

log = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.app/latest"
DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_AGE_MIN = 60


def _fetch_frankfurter(from_ccy: str, to_ccy: str) -> Optional[float]:
    """Chiama Frankfurter per rate from→to. Ritorna float o None se errore."""
    url = f"{FRANKFURTER_URL}?from={from_ccy.upper()}&to={to_ccy.upper()}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MediaFlow/3.5"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as r:
            if r.status != 200:
                log.warning(f"FX provider HTTP {r.status} for {from_ccy}→{to_ccy}")
                return None
            data = json.loads(r.read().decode("utf-8"))
            rate = data.get("rates", {}).get(to_ccy.upper())
            if rate is None:
                log.warning(f"FX provider missing rate {to_ccy} in response for {from_ccy}")
                return None
            return float(rate)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        log.warning(f"FX provider error {from_ccy}→{to_ccy}: {e}")
        return None
    except Exception as e:
        log.exception(f"FX provider unexpected error {from_ccy}→{to_ccy}: {e}")
        return None


def _upsert_rate(db: Session, from_ccy: str, to_ccy: str, rate: float) -> FXRate:
    """Insert o update (single row per coppia). Idempotente."""
    from_u = from_ccy.upper()
    to_u = to_ccy.upper()
    existing = db.query(FXRate).filter(
        FXRate.from_currency == from_u,
        FXRate.to_currency == to_u,
    ).first()
    if existing:
        existing.rate = rate
        existing.fetched_at = now_utc()
        db.commit()
        return existing
    row = FXRate(
        from_currency=from_u, to_currency=to_u,
        rate=rate, fetched_at=now_utc(),
        provider="frankfurter",
    )
    db.add(row)
    db.commit()
    return row


def get_fx_rate(
    db: Session, from_ccy: str, to_ccy: str,
    max_age_minutes: int = DEFAULT_MAX_AGE_MIN,
) -> Optional[float]:
    """Ritorna tasso cache se fresh, altrimenti refresha. None se provider fail.

    Same-currency shortcut: from==to → 1.0.
    """
    from_u = from_ccy.upper()
    to_u = to_ccy.upper()
    if from_u == to_u:
        return 1.0
    existing = db.query(FXRate).filter(
        FXRate.from_currency == from_u,
        FXRate.to_currency == to_u,
    ).first()
    cutoff = now_utc() - timedelta(minutes=max_age_minutes)
    if existing and existing.fetched_at >= cutoff:
        return existing.rate
    # Refresh
    fresh = _fetch_frankfurter(from_u, to_u)
    if fresh is not None:
        _upsert_rate(db, from_u, to_u, fresh)
        return fresh
    # Network fail: ritorna stale se presente, altrimenti None
    if existing:
        log.info(f"FX stale fallback {from_u}→{to_u} = {existing.rate} (fetched {existing.fetched_at})")
        return existing.rate
    return None


def refresh_fx_rate(db: Session, from_ccy: str, to_ccy: str) -> Optional[float]:
    """Forza refresh dal provider. None se fail."""
    from_u = from_ccy.upper()
    to_u = to_ccy.upper()
    if from_u == to_u:
        return 1.0
    fresh = _fetch_frankfurter(from_u, to_u)
    if fresh is None:
        return None
    _upsert_rate(db, from_u, to_u, fresh)
    return fresh


def _fetch_frankfurter_on(from_ccy: str, to_ccy: str, on_date) -> Optional[float]:
    """Tasso BCE storico per una data specifica. Endpoint frankfurter /{YYYY-MM-DD}."""
    ds = on_date.isoformat()
    url = f"https://api.frankfurter.app/{ds}?from={from_ccy.upper()}&to={to_ccy.upper()}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MediaFlow/3.5"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as r:
            if r.status != 200:
                log.warning(f"FX historical HTTP {r.status} {from_ccy}->{to_ccy} {ds}")
                return None
            data = json.loads(r.read().decode("utf-8"))
            rate = data.get("rates", {}).get(to_ccy.upper())
            return float(rate) if rate is not None else None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        log.warning(f"FX historical error {from_ccy}->{to_ccy} {ds}: {e}")
        return None
    except Exception as e:
        log.exception(f"FX historical unexpected {from_ccy}->{to_ccy} {ds}: {e}")
        return None


def get_fx_rate_on(db: Session, from_ccy: str, to_ccy: str, on_date) -> Optional[float]:
    """Tasso BCE alla data `on_date` (per conversione legale all'emissione fattura,
    art. 13 c.4 DPR 633/72). Non usa la cache single-row (storico per-data).
    None se provider fail."""
    if from_ccy.upper() == to_ccy.upper():
        return 1.0
    return _fetch_frankfurter_on(from_ccy, to_ccy, on_date)


def convert(amount: float, from_ccy: str, to_ccy: str, db: Session) -> Optional[float]:
    """Converte amount via cached rate. None se provider fail e no cache.

    v3.5.0-alpha.172.142 (audit) — arrotonda il risultato a 2 cifre HALF_UP
    (prima ritornava float grezzo → valori non arrotondati persistiti nei
    totali Quote)."""
    rate = get_fx_rate(db, from_ccy, to_ccy)
    if rate is None:
        return None
    from app.services.money import to_decimal, money_round, money_to_float
    return money_to_float(money_round(to_decimal(amount) * to_decimal(rate)))
