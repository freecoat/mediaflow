"""
Router Acquisizioni — CRUD + summary + agenda.

Fase 1 Acquisizioni: gestione pipeline commerciale con probabilità pesata.
"""
from __future__ import annotations
from typing import Optional
from decimal import Decimal
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session, selectinload
from app.database import get_db
from app.context import current_tenant_id
from app.models.models import (
    Acquisition, AcquisitionStage, Department, Client, Quote,
)
from app.services.rbac import requires_permission
from app.services.acquisition_service import (
    weighted_value, effective_probability, pipeline_summary, upcoming_actions,
)

router = APIRouter(tags=["acquisitions"])
RequireView = Depends(requires_permission("view_acquisitions"))
RequireManage = Depends(requires_permission("manage_acquisitions"))


def _acq_dict(acq: Acquisition) -> dict:
    return {
        "id": acq.id, "title": acq.title,
        "client_id": acq.client_id,
        "client_name": acq.client.name if acq.client else acq.prospect_name,
        "prospect_name": acq.prospect_name,
        "project_id": acq.project_id,
        "stage": acq.stage.value,
        "estimated_value": str(Decimal(str(acq.estimated_value or 0)).quantize(Decimal("0.01"))),
        "win_probability_pct": acq.win_probability_pct,
        "effective_probability": effective_probability(acq),
        "weighted_value": str(weighted_value(acq)),
        "expected_close_date": acq.expected_close_date.isoformat() if acq.expected_close_date else None,
        "owner_user_id": acq.owner_user_id,
        "next_action": acq.next_action,
        "next_action_date": acq.next_action_date.isoformat() if acq.next_action_date else None,
        "source": acq.source, "lost_reason": acq.lost_reason,
        "departments": [{"id": d.id, "name": d.name} for d in acq.departments],
    }


def _set_departments(db, acq, dept_ids_csv):
    acq.departments.clear()
    for x in (dept_ids_csv or "").split(","):
        x = x.strip()
        if x.isdigit():
            d = db.query(Department).filter(Department.id == int(x),
                                            Department.tenant_id == current_tenant_id()).first()
            if d:
                acq.departments.append(d)


@router.get("/acquisitions/api/list", dependencies=[RequireView])
async def list_acquisitions(stage: Optional[str] = None, department_id: Optional[int] = None,
                            owner_id: Optional[int] = None, client_id: Optional[int] = None,
                            state: Optional[str] = None, db: Session = Depends(get_db)):
    q = (db.query(Acquisition).options(selectinload(Acquisition.departments),
                                       selectinload(Acquisition.client))
         .filter(Acquisition.tenant_id == current_tenant_id(),
                 Acquisition.is_active == True))  # noqa: E712
    if stage:
        q = q.filter(Acquisition.stage == AcquisitionStage(stage))
    if owner_id:
        q = q.filter(Acquisition.owner_user_id == owner_id)
    if client_id:
        q = q.filter(Acquisition.client_id == client_id)
    if state == "won":
        q = q.filter(Acquisition.stage == AcquisitionStage.won)
    elif state == "lost":
        q = q.filter(Acquisition.stage == AcquisitionStage.lost)
    elif state == "open":
        q = q.filter(Acquisition.stage.notin_([AcquisitionStage.won, AcquisitionStage.lost]))
    rows = q.order_by(Acquisition.updated_at.desc()).all()
    if department_id:
        rows = [a for a in rows if any(d.id == department_id for d in a.departments)]
    return {"items": [_acq_dict(a) for a in rows]}


@router.get("/acquisitions/api/summary", dependencies=[RequireView])
async def summary(department_id: Optional[int] = None, owner_id: Optional[int] = None,
                  client_id: Optional[int] = None, db: Session = Depends(get_db)):
    s = pipeline_summary(db, current_tenant_id(), department_id=department_id,
                         owner_id=owner_id, client_id=client_id)
    return {
        "by_stage": {k: {"count": v["count"], "weighted": str(v["weighted"])}
                     for k, v in s["by_stage"].items()},
        "by_department": {k: str(v) for k, v in s["by_department"].items()},
        "total_weighted": str(s["total_weighted"]),
        "open_count": s["open_count"],
    }


@router.get("/acquisitions/api/agenda", dependencies=[RequireView])
async def agenda(owner_id: Optional[int] = None, days: int = 30, db: Session = Depends(get_db)):
    return {"items": upcoming_actions(db, current_tenant_id(), owner_id=owner_id, days=days)}


@router.get("/acquisitions/api/{aid}", dependencies=[RequireView])
async def get_acquisition(aid: int, db: Session = Depends(get_db)):
    acq = (db.query(Acquisition)
           .options(selectinload(Acquisition.departments), selectinload(Acquisition.client))
           .filter(Acquisition.id == aid, Acquisition.tenant_id == current_tenant_id()).first())
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    d = _acq_dict(acq)
    # quotazioni collegate (del progetto o, se assente, del cliente)
    qq = db.query(Quote).filter(Quote.tenant_id == current_tenant_id())
    if acq.project_id:
        qq = qq.filter(Quote.project_id == acq.project_id)
    elif acq.client_id:
        qq = qq.filter(Quote.client_id == acq.client_id)
    else:
        qq = qq.filter(False)
    d["quotes"] = [{"id": q.id, "number": q.number, "status": q.status.value,
                    "total_with_vat": q.total_with_vat} for q in qq.all()]
    return d


def _parse_date(v):
    return date.fromisoformat(v) if v else None


@router.post("/acquisitions/api", dependencies=[RequireManage])
async def create_acquisition(request: Request, title: str = Form(...),
                             client_id: Optional[int] = Form(None),
                             prospect_name: Optional[str] = Form(None),
                             stage: str = Form("lead"),
                             estimated_value: float = Form(0),
                             win_probability_pct: Optional[float] = Form(None),
                             expected_close_date: Optional[str] = Form(None),
                             owner_user_id: Optional[int] = Form(None),
                             next_action: Optional[str] = Form(None),
                             next_action_date: Optional[str] = Form(None),
                             source: Optional[str] = Form(None),
                             department_ids: Optional[str] = Form(None),
                             db: Session = Depends(get_db)):
    from app.services.rbac import current_user_optional
    u = current_user_optional(request)
    acq = Acquisition(tenant_id=current_tenant_id(), title=title.strip(),
                      client_id=client_id, prospect_name=(prospect_name or None),
                      stage=AcquisitionStage(stage), estimated_value=estimated_value,
                      win_probability_pct=win_probability_pct,
                      expected_close_date=_parse_date(expected_close_date),
                      owner_user_id=owner_user_id or (u.id if u else None),
                      next_action=next_action, next_action_date=_parse_date(next_action_date),
                      source=source, created_by=(u.id if u else None))
    db.add(acq); db.flush()
    _set_departments(db, acq, department_ids)
    db.commit(); db.refresh(acq)
    return _acq_dict(acq)


@router.put("/acquisitions/api/{aid}", dependencies=[RequireManage])
async def update_acquisition(aid: int, title: Optional[str] = Form(None),
                             client_id: Optional[int] = Form(None),
                             prospect_name: Optional[str] = Form(None),
                             estimated_value: Optional[float] = Form(None),
                             win_probability_pct: Optional[float] = Form(None),
                             expected_close_date: Optional[str] = Form(None),
                             owner_user_id: Optional[int] = Form(None),
                             next_action: Optional[str] = Form(None),
                             next_action_date: Optional[str] = Form(None),
                             source: Optional[str] = Form(None),
                             lost_reason: Optional[str] = Form(None),
                             department_ids: Optional[str] = Form(None),
                             db: Session = Depends(get_db)):
    acq = (db.query(Acquisition)
           .options(selectinload(Acquisition.departments), selectinload(Acquisition.client))
           .filter(Acquisition.id == aid, Acquisition.tenant_id == current_tenant_id()).first())
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    if title is not None: acq.title = title.strip()
    if client_id is not None: acq.client_id = client_id or None
    if prospect_name is not None: acq.prospect_name = prospect_name or None
    if estimated_value is not None: acq.estimated_value = estimated_value
    if win_probability_pct is not None: acq.win_probability_pct = win_probability_pct
    if expected_close_date is not None: acq.expected_close_date = _parse_date(expected_close_date)
    if owner_user_id is not None: acq.owner_user_id = owner_user_id or None
    if next_action is not None: acq.next_action = next_action or None
    if next_action_date is not None: acq.next_action_date = _parse_date(next_action_date)
    if source is not None: acq.source = source or None
    if lost_reason is not None: acq.lost_reason = lost_reason or None
    if department_ids is not None: _set_departments(db, acq, department_ids)
    db.commit(); db.refresh(acq)
    return _acq_dict(acq)


@router.delete("/acquisitions/api/{aid}", dependencies=[RequireManage])
async def delete_acquisition(aid: int, db: Session = Depends(get_db)):
    acq = db.query(Acquisition).filter(Acquisition.id == aid,
                                       Acquisition.tenant_id == current_tenant_id()).first()
    if not acq:
        raise HTTPException(404, "Acquisizione non trovata")
    acq.is_active = False
    db.commit()
    return {"ok": True, "id": aid}
