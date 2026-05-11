"""
MediaFlow — servizio finanziario
Calcolo P&L per job, totali fatture, report.
"""
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_, and_
from app.models import (
    Job, Timesheet, Expense, Invoice, InvoiceStatus,
    Department, JobCostLine, PriceItem,
)


def job_financial_summary(db: Session, job_id: int) -> dict:
    """
    Restituisce un dizionario con i dati economici del job:
    ricavi attesi, ore lavorate, spese, fatturato, margine.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return {}

    # Ore × tariffa
    timesheets = db.query(Timesheet).filter(
        Timesheet.job_id == job_id, Timesheet.is_billable == True
    ).all()
    hours_cost = sum(
        (t.hours * t.hourly_rate) for t in timesheets if t.hourly_rate
    )
    total_hours = sum(t.hours for t in timesheets)

    # Spese fatturabili
    expenses = db.query(Expense).filter(
        Expense.job_id == job_id, Expense.is_billable == True
    ).all()
    total_expenses = sum(e.amount for e in expenses)

    # Fatturato (solo fatture pagate)
    invoiced = db.query(func.sum(Invoice.total)).filter(
        Invoice.job_id == job_id,
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.paid])
    ).scalar() or 0.0

    paid = db.query(func.sum(Invoice.total)).filter(
        Invoice.job_id == job_id,
        Invoice.status == InvoiceStatus.paid
    ).scalar() or 0.0

    costs = hours_cost + total_expenses
    margin = (job.budget_quoted or 0) - costs

    return {
        "job_id": job_id,
        "title": job.title,
        "budget": job.budget_quoted or 0,
        "total_hours": round(total_hours, 2),
        "hours_cost": round(hours_cost, 2),
        "total_expenses": round(total_expenses, 2),
        "total_costs": round(costs, 2),
        "invoiced": round(invoiced, 2),
        "paid": round(paid, 2),
        "margin": round(margin, 2),
        "margin_pct": round((margin / job.budget_quoted * 100) if job.budget_quoted else 0, 1),
    }


def company_pl_summary(db: Session, year: int) -> dict:
    """P&L aggregato per anno."""
    from datetime import date

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    revenue = db.query(func.sum(Invoice.total)).filter(
        Invoice.issue_date.between(start, end),
        Invoice.status.in_([InvoiceStatus.sent, InvoiceStatus.paid])
    ).scalar() or 0.0

    costs = db.query(func.sum(Expense.amount)).filter(
        Expense.expense_date.between(start, end)
    ).scalar() or 0.0

    hours = db.query(func.sum(Timesheet.hours)).filter(
        Timesheet.work_date.between(start, end)
    ).scalar() or 0.0

    return {
        "year": year,
        "revenue": round(revenue, 2),
        "costs": round(costs, 2),
        "gross_margin": round(revenue - costs, 2),
        "total_hours": round(hours, 2),
    }


def departments_pl_summary(db: Session, year: int) -> dict:
    """Aggregato P&L per reparto, anno corrente.

    Semantica (proxy, non rigorosa):
      - revenue = SUM(JobCostLine.total_accrued WHERE is_billable=True),
        raggruppato per PriceItem.department_id.
      - cost    = SUM(JobCostLine.total_accrued WHERE is_billable=False),
        raggruppato per PriceItem.department_id (hardcost interni
        allocati al reparto attraverso la voce di listino).

    Filtro temporale via Job.start_date OR Job.end_date intersezione
    con l'anno (i JCL senza Job in periodo vengono esclusi). Le
    JCL senza price_item (riga libera senza link al listino) finiscono
    in un bucket "_unallocated" se hanno almeno valore non nullo.

    NB: questa è un'approssimazione visiva per la dashboard. Per il
    cost report rigoroso vedi `/cost-report` dettaglio job-by-job.
    """
    from datetime import date

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    in_year = or_(
        and_(Job.start_date.isnot(None), Job.start_date >= start, Job.start_date <= end),
        and_(Job.end_date.isnot(None), Job.end_date >= start, Job.end_date <= end),
    )

    lines = (
        db.query(JobCostLine)
        .options(
            joinedload(JobCostLine.job),
            joinedload(JobCostLine.price_item),
        )
        .join(Job, JobCostLine.job_id == Job.id)
        .filter(in_year)
        .all()
    )

    departments = {d.id: d for d in db.query(Department).all()}
    agg = {}
    unalloc = {"id": None, "name": "Non allocato", "revenue": 0.0, "cost": 0.0}
    for jcl in lines:
        amount = jcl.total_accrued or 0.0
        if amount == 0:
            continue
        dept_id = None
        if jcl.price_item is not None:
            dept_id = jcl.price_item.department_id
        if dept_id is None:
            bucket = unalloc
        else:
            if dept_id not in agg:
                dept = departments.get(dept_id)
                agg[dept_id] = {
                    "id": dept_id,
                    "name": dept.name if dept else f"Reparto #{dept_id}",
                    "revenue": 0.0,
                    "cost": 0.0,
                }
            bucket = agg[dept_id]
        if jcl.is_billable:
            bucket["revenue"] += amount
        else:
            bucket["cost"] += amount

    rows = list(agg.values())
    if unalloc["revenue"] or unalloc["cost"]:
        rows.append(unalloc)
    for r in rows:
        r["revenue"] = round(r["revenue"], 2)
        r["cost"] = round(r["cost"], 2)
        r["margin"] = round(r["revenue"] - r["cost"], 2)
    rows.sort(key=lambda r: r["revenue"] + r["cost"], reverse=True)
    return {"year": year, "departments": rows}
