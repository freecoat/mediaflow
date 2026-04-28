"""
MediaFlow — servizio finanziario
Calcolo P&L per job, totali fatture, report.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models import Job, Timesheet, Expense, Invoice, InvoiceStatus


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
