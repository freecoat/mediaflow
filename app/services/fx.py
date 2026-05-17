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
        existing.fetched_at = datetime.utcnow()
        db.commit()
        return existing
    row = FXRate(
        from_currency=from_u, to_currency=to_u,
        rate=rate, fetched_at=datetime.utcnow(),
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
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
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


def convert(amount: float, from_ccy: str, to_ccy: str, db: Session) -> Optional[float]:
    """Converte amount via cached rate. None se provider fail e no cache."""
    rate = get_fx_rate(db, from_ccy, to_ccy)
    if rate is None:
        return None
    return amount * rate
