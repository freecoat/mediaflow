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
from app.models import Job, JobCostLine, Timesheet, Expense, Invoice, InvoiceStatus, JobResourceAssignment

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
