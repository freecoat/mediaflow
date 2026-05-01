"""
Router Cost Report — rendicontazione per job vs quotazione, Over/Under analysis.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Response
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models import (
    Job, JobCostLine, Timesheet, Expense, Invoice, InvoiceStatus, JobResourceAssignment,
    Booking, BookingAssignment, BookingExecutionStatus, BookingOvertimeStatus, BookingStatus,
    Resource, WorkingHoursPolicy,
)
from app.services.booking_cost import compute_assignment_breakdown, BookingBreakdown
from app.services.working_hours import get_holidays

router = APIRouter(prefix="/cost-report", tags=["cost_report"])


def _tpl():
    from app.main import templates
    return templates


@router.get("/", response_class=HTMLResponse)
async def cost_report_page(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).options(joinedload(Job.client)).all()
    return _tpl().TemplateResponse("pages/cost_report.html", {"request": request, "jobs": jobs})


@router.get("/api/job/{job_id}")
async def job_cost_report(job_id: int, db: Session = Depends(get_db)):
    """Report completo: quotazione vs reale (accrued/expected), Over/Under."""
    job = db.query(Job).options(
        joinedload(Job.client),
        joinedload(Job.quote),
        joinedload(Job.cost_lines).joinedload(JobCostLine.price_item),
        joinedload(Job.resource_assignments).joinedload(JobResourceAssignment.resource),
    ).filter(Job.id == job_id).first()
    if not job: raise HTTPException(404, "Job non trovato")
    
    # Ore lavorate per risorsa
    ts_data = db.query(
        Timesheet.user_id,
        func.sum(Timesheet.hours).label("hours"),
        func.sum(Timesheet.hours * Timesheet.hourly_rate).label("cost"),
    ).filter(Timesheet.job_id == job_id).group_by(Timesheet.user_id).all()
    
    # Spese
    total_expenses = db.query(func.sum(Expense.amount)).filter(
        Expense.job_id == job_id).scalar() or 0
    
    # Fatturato
    invoiced = db.query(func.sum(Invoice.total)).filter(
        Invoice.job_id == job_id,
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.paid])
    ).scalar() or 0
    paid = db.query(func.sum(Invoice.total)).filter(
        Invoice.job_id == job_id, Invoice.status == InvoiceStatus.paid
    ).scalar() or 0
    
    # Totali cost lines
    total_quoted = sum(l.total_quoted for l in job.cost_lines)
    total_accrued = sum(l.total_accrued for l in job.cost_lines)
    total_expected = sum(l.total_expected for l in job.cost_lines)
    total_actual_hours_cost = sum(r.cost or 0 for r in ts_data)
    
    return {
        "job": {
            "id": job.id, "code": job.code, "title": job.title,
            "status": job.status,
            "client": job.client.name if job.client else None,
            "budget_quoted": job.budget_quoted,
            "start_date": str(job.start_date) if job.start_date else None,
            "end_date": str(job.end_date) if job.end_date else None,
        },
        "summary": {
            "budget_quoted": round(job.budget_quoted, 2),
            "total_quoted": round(total_quoted, 2),
            "total_accrued": round(total_accrued, 2),
            "total_expected": round(total_expected, 2),
            "over_under": round(job.budget_quoted - total_expected, 2),
            "total_expenses": round(total_expenses, 2),
            "hours_cost": round(total_actual_hours_cost, 2),
            "invoiced": round(invoiced, 2),
            "paid": round(paid, 2),
        },
        "cost_lines": [
            {
                "id": l.id, "description": l.description, "unit": l.unit,
                "quantity_quoted": l.quantity_quoted,
                "quantity_actual": l.quantity_actual,
                "unit_price": l.unit_price,
                "total_quoted": l.total_quoted,
                "total_accrued": l.total_accrued,
                "total_expected": l.total_expected,
                "over_under": round(l.total_quoted - l.total_expected, 2),
                "is_billable": l.is_billable,
                "category": l.price_item.category.name if l.price_item and l.price_item.category else None,
            }
            for l in job.cost_lines
        ],
        "resource_assignments": [
            {
                "resource": a.resource.name if a.resource else None,
                "type": a.resource.type if a.resource else None,
                "role": a.role_in_project,
                "planned_days": a.planned_days,
                "planned_hours": a.planned_hours,
                "agreed_daily_rate": a.agreed_daily_rate,
                "agreed_hourly_rate": a.agreed_hourly_rate,
            }
            for a in job.resource_assignments
        ],
        "timesheet_summary": [
            {
                "user_id": r.user_id,
                "hours": round(r.hours, 2),
                "cost": round(r.cost or 0, 2),
            }
            for r in ts_data
        ],
    }


@router.put("/api/job/{job_id}/cost-lines/{line_id}")
async def update_cost_line(
    job_id: int, line_id: int,
    quantity_actual: Optional[float] = Form(None),
    total_accrued: Optional[float] = Form(None),
    total_expected: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    line = db.query(JobCostLine).filter(
        JobCostLine.id == line_id, JobCostLine.job_id == job_id).first()
    if not line: raise HTTPException(404)
    if quantity_actual is not None:
        line.quantity_actual = quantity_actual
        line.total_accrued = round(quantity_actual * line.unit_price, 2)
    if total_accrued is not None: line.total_accrued = total_accrued
    if total_expected is not None: line.total_expected = total_expected
    if notes is not None: line.notes = notes
    db.commit()
    return {"id": line.id, "total_accrued": line.total_accrued, "total_expected": line.total_expected}


@router.post("/api/job/{job_id}/assign-resource")
async def assign_resource(
    job_id: int,
    resource_id: int = Form(...),
    role_in_project: Optional[str] = Form(None),
    planned_days: Optional[float] = Form(None),
    planned_hours: Optional[float] = Form(None),
    agreed_daily_rate: Optional[float] = Form(None),
    agreed_hourly_rate: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    assignment = JobResourceAssignment(
        job_id=job_id, resource_id=resource_id,
        role_in_project=role_in_project,
        planned_days=planned_days, planned_hours=planned_hours,
        agreed_daily_rate=agreed_daily_rate, agreed_hourly_rate=agreed_hourly_rate,
        notes=notes,
    )
    db.add(assignment); db.commit(); db.refresh(assignment)
    return {"id": assignment.id}


@router.delete("/api/job/{job_id}/assign-resource/{assignment_id}")
async def remove_resource_assignment(
    job_id: int, assignment_id: int, db: Session = Depends(get_db)):
    a = db.query(JobResourceAssignment).filter(
        JobResourceAssignment.id == assignment_id, JobResourceAssignment.job_id == job_id).first()
    if not a: raise HTTPException(404)
    db.delete(a); db.commit()
    return {"ok": True}


# ── Booking executive cost report (v3.4.32) ─────────────────────────
# Aggrega i booking di un job per fascia (regular / overtime / pending /
# notturno / festivo / domenica) + pool not_done (booking con
# execution_status=not_done & count_in_costs=False, escluse dai totali).
#
# Nota strategica (vedi memoria project_costreport_vs_timesheet.md):
# il cost report parte dai BOOKING, non dai TimePunch. Le timbrature sono
# binario HR separato. Questo endpoint è il primo passo verso il rifacimento
# del cost report; per ora coabita con il vecchio /api/job/{id} basato
# su Timesheet.

def _resource_policy(resource: Resource, db: Session) -> Optional[WorkingHoursPolicy]:
    if resource.working_hours_policy_id and resource.working_hours_policy:
        return resource.working_hours_policy
    return db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.is_default == True  # noqa: E712
    ).first()


@router.get("/api/job/{job_id}/booking-summary")
async def job_booking_summary(job_id: int, db: Session = Depends(get_db)):
    """Aggrega i booking del job per fascia oraria + pool not_done.

    Ritorna:
      - totals: BookingBreakdown cumulato per booking conteggiati
      - pending_overtime: lista booking con overtime_status=pending (azione richiesta)
      - not_done_pool: lista booking not_done con count_in_costs=False (pool)
      - by_resource: breakdown per risorsa (per riga finanziaria)
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job non trovato")

    bookings = (
        db.query(Booking)
        .options(
            joinedload(Booking.assignments).joinedload(BookingAssignment.resource),
            joinedload(Booking.cost_line),
        )
        .filter(
            Booking.job_id == job_id,
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )

    totals = BookingBreakdown()
    by_resource: dict[int, dict] = {}
    pending_overtime = []
    not_done_pool = []

    # holidays cache per anno (compute una sola volta)
    holidays_cache: dict[tuple[int, int], set] = {}

    def _get_hol(policy, y0, y1):
        key = (id(policy), y0, y1)
        if key not in holidays_cache:
            holidays_cache[key] = get_holidays(policy, y0, y1)
        return holidays_cache[key]

    for b in bookings:
        # Pending overtime: tracciato a parte (mostra ore stimate ma non sommate)
        if b.overtime_status == BookingOvertimeStatus.pending:
            pending_overtime.append({
                "booking_id": b.id,
                "start": b.start_datetime.isoformat() if b.start_datetime else None,
                "end": b.end_datetime.isoformat() if b.end_datetime else None,
                "cost_line": b.cost_line.description if b.cost_line else None,
                "resources": [a.resource.name for a in b.assignments if a.resource],
                "notes": b.notes,
            })

        # Pool not_done: tracciato a parte
        if (b.execution_status == BookingExecutionStatus.not_done
            and not b.count_in_costs):
            tot_h = sum(
                (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
                for a in b.assignments
            )
            not_done_pool.append({
                "booking_id": b.id,
                "start": b.start_datetime.isoformat() if b.start_datetime else None,
                "end": b.end_datetime.isoformat() if b.end_datetime else None,
                "cost_line": b.cost_line.description if b.cost_line else None,
                "resources": [a.resource.name for a in b.assignments if a.resource],
                "reason": b.not_done_reason,
                "total_hours": round(tot_h, 2),
            })
            # Saltato dal totals (vedi compute_assignment_breakdown che riconosce il pool)

        # Aggrega comunque tramite breakdown (gestisce internamente pool/pending)
        for a in b.assignments:
            if not a.resource:
                continue
            policy = _resource_policy(a.resource, db)
            if not policy:
                continue
            hols = _get_hol(policy, a.start_datetime.year, a.end_datetime.year)
            br = compute_assignment_breakdown(a, policy, hols, b)
            totals.add(br)
            rmap = by_resource.setdefault(a.resource.id, {
                "resource_id": a.resource.id,
                "resource_name": a.resource.name,
                "rate": a.resource.daily_rate or a.resource.hourly_rate or 0,
                "breakdown": BookingBreakdown(),
            })
            rmap["breakdown"].add(br)

    return {
        "job": {"id": job.id, "code": job.code, "title": job.title},
        "totals": totals.as_dict(),
        "by_resource": [
            {
                "resource_id": r["resource_id"],
                "resource_name": r["resource_name"],
                "rate": r["rate"],
                "breakdown": r["breakdown"].as_dict(),
            }
            for r in by_resource.values()
        ],
        "pending_overtime": pending_overtime,
        "not_done_pool": not_done_pool,
    }


@router.post("/api/job/{job_id}/not-done-pool/{booking_id}/discard")
async def discard_not_done_pool_booking(
    job_id: int, booking_id: int, db: Session = Depends(get_db),
):
    """Scarta definitivamente un booking not_done dal pool: cancella il booking
    (status=cancelled). Le ore non risulteranno mai conteggiate."""
    b = db.query(Booking).filter(
        Booking.id == booking_id, Booking.job_id == job_id,
    ).first()
    if not b:
        raise HTTPException(404, "Booking non trovato")
    b.status = BookingStatus.cancelled
    db.commit()
    return {"ok": True, "id": b.id, "status": "cancelled"}
