"""Servizio Acquisizioni — probabilità, potenziale pesato, summary, agenda,
conversione a progetto. Decimal per i valori monetari."""
from __future__ import annotations
from decimal import Decimal
from app.models.models import Acquisition, AcquisitionStage

DEFAULT_ACQ_PROBABILITY: dict[AcquisitionStage, float] = {
    AcquisitionStage.lead: 10,
    AcquisitionStage.qualified: 30,
    AcquisitionStage.quoting: 50,
    AcquisitionStage.negotiation: 70,
    AcquisitionStage.won: 100,
    AcquisitionStage.lost: 0,
}


def effective_probability(acq: Acquisition) -> float:
    if acq.win_probability_pct is not None:
        return float(acq.win_probability_pct)
    return float(DEFAULT_ACQ_PROBABILITY.get(acq.stage, 0))


def weighted_value(acq: Acquisition) -> Decimal:
    val = Decimal(str(acq.estimated_value or 0))
    prob = Decimal(str(effective_probability(acq))) / Decimal("100")
    return (val * prob).quantize(Decimal("0.01"))
