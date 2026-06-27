from decimal import Decimal
from app.models.models import Acquisition, AcquisitionStage
from app.services.acquisition_service import (
    effective_probability, weighted_value, DEFAULT_ACQ_PROBABILITY,
)


def test_default_probability_by_stage():
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.lead] == 10
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.negotiation] == 70
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.won] == 100
    assert DEFAULT_ACQ_PROBABILITY[AcquisitionStage.lost] == 0


def test_effective_probability_override_wins():
    acq = Acquisition(stage=AcquisitionStage.lead, win_probability_pct=42)
    assert effective_probability(acq) == 42
    acq2 = Acquisition(stage=AcquisitionStage.quoting, win_probability_pct=None)
    assert effective_probability(acq2) == 50


def test_weighted_value():
    acq = Acquisition(stage=AcquisitionStage.negotiation,
                      estimated_value=Decimal("80000"), win_probability_pct=None)
    assert weighted_value(acq) == Decimal("56000.00")  # 80000 * 0.70
