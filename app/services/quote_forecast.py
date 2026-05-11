"""v3.5.0-alpha.77 — Forecast finanziario quote (sales pipeline).

Pattern Salesforce/HubSpot/Pipedrive: ogni quote ha una probabilità di
chiusura associata allo stage, esposta in dashboards come:
  - Pipeline value (raw): Σ total quote in pipeline (not closed)
  - Weighted forecast: Σ (total × probability/100)
  - Bookings: somma quote approved nel periodo
  - Lost: quote rejected/expired

DEFAULT_WIN_PROBABILITY mapping da status:
  draft       → 10  (interno, work-in-progress)
  sent        → 30  (cliente sta valutando)
  approved    → 90  (firmato, residuo rischio operativo)
  expired     → 5   (vecchia, riattivabile)
  rejected    → 0
  superseded  → 0   (rimpiazzato da versione successiva)
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import extract

from app.models import Quote, QuoteStatus


DEFAULT_WIN_PROBABILITY = {
    QuoteStatus.draft:      10,
    QuoteStatus.sent:       30,
    QuoteStatus.approved:   90,
    QuoteStatus.expired:    5,
    QuoteStatus.rejected:   0,
    QuoteStatus.superseded: 0,
}


def quote_probability(q: Quote) -> float:
    """Ritorna probability_pct effettiva (override manuale o default)."""
    if q.win_probability_pct is not None:
        return max(0.0, min(100.0, float(q.win_probability_pct)))
    return float(DEFAULT_WIN_PROBABILITY.get(q.status, 0))


def quote_weighted_value(q: Quote) -> float:
    """Valore pesato = total × probability/100."""
    return round((q.total_with_vat or 0.0) * quote_probability(q) / 100.0, 2)


def quote_expected_close(q: Quote) -> date:
    """expected_close_date override o default (issue + 30gg)."""
    if q.expected_close_date:
        return q.expected_close_date
    if q.issue_date:
        return q.issue_date + timedelta(days=30)
    from datetime import date as _d
    return _d.today()


def yearly_forecast(db: Session, year: int, *,
                    project_id: Optional[int] = None,
                    client_id: Optional[int] = None,
                    tenant_id: int = 1) -> dict:
    """Forecast mensile per anno. Ritorna dict con:
      - months: lista 1..12 con stage breakdown + weighted + pipeline
      - totals: aggregati anno
      - win_rate, average_deal_size
    """
    q = db.query(Quote).filter(
        Quote.tenant_id == tenant_id,
    )
    # Filter: quote rilevanti per l'anno = expected_close_date nell'anno
    # OPPURE issue_date nell'anno (per legacy senza expected_close_date)
    if project_id: q = q.filter(Quote.project_id == project_id)
    if client_id: q = q.filter(Quote.client_id == client_id)
    quotes = q.all()
    series = [
        {
            "month": m,
            "pipeline_total": 0.0,            # raw Σ total per quote ancora "vive"
            "weighted_forecast": 0.0,          # pipeline pesata
            "draft": 0.0,
            "sent": 0.0,
            "approved": 0.0,
            "rejected": 0.0,
            "expired": 0.0,
            "count_draft": 0,
            "count_sent": 0,
            "count_approved": 0,
            "count_rejected": 0,
            "count_expired": 0,
        }
        for m in range(1, 13)
    ]
    # Stats annuali
    tot_pipeline = 0.0
    tot_weighted = 0.0
    tot_won_value = 0.0
    tot_lost_value = 0.0
    n_won = 0
    n_lost = 0
    n_total_decisione = 0  # approved+rejected (closing)
    for qt in quotes:
        ec = quote_expected_close(qt)
        if ec.year != year:
            continue
        m = ec.month - 1
        total = qt.total_with_vat or 0.0
        status_key = qt.status.value if hasattr(qt.status, "value") else str(qt.status)
        prob = quote_probability(qt)
        weighted = total * prob / 100.0
        if status_key in series[m]:
            series[m][status_key] += total
            series[m]["count_" + status_key] += 1
        if status_key in ("draft", "sent", "approved", "expired"):
            # Pipeline = quote non rejected/superseded
            series[m]["pipeline_total"] += total
            series[m]["weighted_forecast"] += weighted
            tot_pipeline += total
            tot_weighted += weighted
        if status_key == "approved":
            n_won += 1; tot_won_value += total
            n_total_decisione += 1
        if status_key == "rejected":
            n_lost += 1; tot_lost_value += total
            n_total_decisione += 1
    for s in series:
        for k in ("pipeline_total", "weighted_forecast", "draft", "sent",
                  "approved", "rejected", "expired"):
            s[k] = round(s[k], 2)
    win_rate = round(n_won / n_total_decisione * 100, 1) if n_total_decisione else None
    avg_deal_won = round(tot_won_value / n_won, 2) if n_won else None
    return {
        "year": year,
        "months": series,
        "totals": {
            "pipeline_total": round(tot_pipeline, 2),
            "weighted_forecast": round(tot_weighted, 2),
            "won_value": round(tot_won_value, 2),
            "lost_value": round(tot_lost_value, 2),
            "n_won": n_won,
            "n_lost": n_lost,
            "win_rate_pct": win_rate,
            "average_deal_size": avg_deal_won,
        },
    }
