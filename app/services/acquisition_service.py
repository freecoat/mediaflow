"""Servizio Acquisizioni — probabilità, potenziale pesato, summary, agenda,
conversione a progetto. Decimal per i valori monetari."""
from __future__ import annotations
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy.orm import Session, selectinload
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


_OPEN_STAGES = {AcquisitionStage.lead, AcquisitionStage.qualified,
                AcquisitionStage.quoting, AcquisitionStage.negotiation}


def _filtered_query(db: Session, tenant_id, department_id, owner_id, client_id):
    from app.models.models import Acquisition as A, acquisition_departments
    q = (db.query(A).options(selectinload(A.departments))
         .filter(A.tenant_id == tenant_id, A.is_active == True))  # noqa: E712
    if owner_id:
        q = q.filter(A.owner_user_id == owner_id)
    if client_id:
        q = q.filter(A.client_id == client_id)
    if department_id:
        q = q.join(acquisition_departments).filter(
            acquisition_departments.c.department_id == department_id)
    return q


def pipeline_summary(db, tenant_id, *, department_id=None, owner_id=None, client_id=None):
    rows = _filtered_query(db, tenant_id, department_id, owner_id, client_id).all()
    by_stage, by_department = {}, {}
    total = Decimal("0.00"); open_count = 0
    for acq in rows:
        w = weighted_value(acq)
        total += w
        st = acq.stage.value
        agg = by_stage.setdefault(st, {"count": 0, "weighted": Decimal("0.00")})
        agg["count"] += 1; agg["weighted"] += w
        if acq.stage in _OPEN_STAGES:
            open_count += 1
        for d in acq.departments:
            by_department[d.name] = by_department.get(d.name, Decimal("0.00")) + w
    return {"by_stage": by_stage, "by_department": by_department,
            "total_weighted": total, "open_count": open_count}


def upcoming_actions(db, tenant_id, *, owner_id=None, days=30):
    from app.models.models import Acquisition as A, Activity
    horizon = date.today() + timedelta(days=days)
    out = []
    aq = (db.query(A).filter(A.tenant_id == tenant_id, A.is_active == True,  # noqa: E712
                             A.next_action_date.isnot(None),
                             A.next_action_date <= horizon))
    if owner_id:
        aq = aq.filter(A.owner_user_id == owner_id)
    for acq in aq.all():
        out.append({"kind": "acquisition", "id": acq.id, "acquisition_id": acq.id,
                    "title": acq.next_action or acq.title, "date": acq.next_action_date.isoformat()})
    act = (db.query(Activity).filter(Activity.tenant_id == tenant_id,
                                     Activity.is_active == True,  # noqa: E712
                                     Activity.next_action_date.isnot(None),
                                     Activity.next_action_date <= horizon))
    for a in act.all():
        out.append({"kind": "activity", "id": a.id, "acquisition_id": a.acquisition_id,
                    "title": a.subject, "date": a.next_action_date.isoformat()})
    out.sort(key=lambda x: x["date"])
    return out
