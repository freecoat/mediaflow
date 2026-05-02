"""
Job extras — reverse-flow: crea Job + JobCostLine(is_extra=True) da un booking
su progetto senza quotazione.

Principio architetturale (v3.4.51):
- Forward (canonica): Quote.approved → Job auto-creato, budget = quote totale
- Reverse (eccezione): Booking su progetto senza quote → modal blocking →
  l'utente sceglie "Nuovo job extra" o "Aggiungi al job extra esistente" →
  Job nasce con budget_quoted=0; ogni JobCostLine(is_extra=True) ricalcola
  budget_quoted = sum(extras.total_expected). Il job appare in
  /finance > Anomalie > Job orfani finché non viene gestito (fatturato a parte
  o scrutto off in cost report).
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Job, JobCostLine, JobStatus, PriceItem, Project


def next_job_code(db: Session, project: Project) -> str:
    """Genera codice job '{PROJECT_CODE}-J{N}' progressivo per quel progetto.
    Stesso pattern di app.routers.quotes._next_job_code."""
    base = (project.code or f"P{project.id}").strip()
    used = {j.code for j in project.jobs if j.code}
    n = 1
    while f"{base}-J{n}" in used:
        n += 1
    return f"{base}-J{n}"


def recompute_budget_from_extras(db: Session, job: Job) -> float:
    """Per job reverse-flow (no quote_id): budget_quoted = somma extras (total_expected).
    Per job quote-driven: NO-OP (budget = quote totale, intoccabile)."""
    if job.quote_id is not None:
        return job.budget_quoted
    total = 0.0
    for line in job.cost_lines:
        if line.is_extra:
            total += line.total_expected or 0.0
    job.budget_quoted = round(total, 2)
    return job.budget_quoted


def create_extra_job_for_project(
    db: Session, project: Project, title: Optional[str] = None
) -> Job:
    """Crea Job 'reverse' (senza quote_id) sul progetto. budget_quoted=0 iniziale."""
    job = Job(
        code=next_job_code(db, project),
        title=(title or f"Extra — {project.title}").strip()[:255],
        project_id=project.id,
        client_id=project.client_id,
        quote_id=None,
        status=JobStatus.active,
        budget_quoted=0.0,
    )
    db.add(job)
    db.flush()
    return job


def add_extra_cost_line(
    db: Session,
    job: Job,
    *,
    description: str,
    quantity: float,
    unit: str = "day",
    unit_price: float = 0.0,
    price_item_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> JobCostLine:
    """Aggiunge JobCostLine(is_extra=True) e ricalcola budget se job reverse-flow."""
    if quantity <= 0:
        raise HTTPException(400, "quantity deve essere > 0")
    total = round(quantity * (unit_price or 0.0), 2)
    line = JobCostLine(
        price_item_id=price_item_id,
        description=description.strip(),
        quantity_quoted=0.0,
        quantity_actual=0.0,
        unit=unit or "day",
        unit_price=unit_price or 0.0,
        total_quoted=0.0,
        total_expected=total,
        is_extra=True,
        is_billable=True,
        notes=notes,
    )
    # Assegno la relationship esplicitamente: SQLAlchemy popola entrambi i lati
    # (Job.cost_lines + JobCostLine.job_id) e job.cost_lines è subito coerente
    # per il successivo recompute_budget_from_extras().
    line.job = job
    db.add(line)
    db.flush()
    recompute_budget_from_extras(db, job)
    return line


def hydrate_from_price_item(
    db: Session,
    price_item_id: int,
    description: str = "",
    unit: str = "day",
    unit_price: float = 0.0,
) -> tuple[str, str, float]:
    """Riempie campi mancanti dalla voce listino. Ritorna (description, unit, unit_price)."""
    pi = db.query(PriceItem).filter(PriceItem.id == price_item_id).first()
    if not pi:
        return description, unit, unit_price
    if not description:
        description = pi.name
    if not unit_price or unit_price <= 0:
        unit_price = pi.price_list or 0.0
    if unit == "day" and pi.unit:
        unit = pi.unit
    return description, unit, unit_price
