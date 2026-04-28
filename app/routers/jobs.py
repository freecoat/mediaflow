"""
Router /jobs — pagina dettaglio job con tabella lavorazioni e aggregazioni ore.

Le lavorazioni (`JobCostLine`) sono first-class:
- ore quotate (`quantity_quoted`) ← dalla riga quote da cui derivano
- ore pianificate ← somma durate Booking sul job (status != cancelled)
  con riferimento esplicito alla lavorazione (Booking.job_cost_line_id arriva
  in v3.4.10; per ora le ore pianificate sono attribuite "al job" generico
  e non alla singola lavorazione)
- ore lavorate ← somma durate TimePunch chiusi sul job
- ore extra ← max(0, lavorate - quotate) per lavorazioni standard,
  oppure intero quantity_actual se is_extra=True (extra puro)

L'operatore può aggiungere lavorazioni extra a posteriori (cliente chiede
upres) e il sistema le marca con `is_extra=True` per la rendicontazione.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Job, JobStatus, JobCostLine, Booking, BookingStatus,
    TimePunch, Project, Client, PriceItem, PriceCategory,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

CURRENT_TENANT = 1


def _tpl():
    from app.main import templates
    return templates


def _aggregate_planned_hours(db: Session, job_id: int, cost_line_id: Optional[int] = None) -> float:
    """Ore pianificate: somma di (end - start) sui Booking attivi.
    Se `cost_line_id` è valorizzato → solo i booking legati a quella riga.
    Altrimenti → tutti i booking del job (anche senza cost_line_id assegnato)."""
    q = db.query(Booking).filter(
        Booking.job_id == job_id,
        Booking.status != BookingStatus.cancelled,
    )
    if cost_line_id is not None:
        q = q.filter(Booking.job_cost_line_id == cost_line_id)
    total = 0.0
    for b in q.all():
        if b.start_datetime and b.end_datetime:
            total += (b.end_datetime - b.start_datetime).total_seconds() / 3600.0
    return round(total, 2)


def _aggregate_actual_hours(db: Session, job_id: int, cost_line_id: Optional[int] = None) -> float:
    """Ore lavorate: somma di (end - start) sui TimePunch chiusi.
    Se `cost_line_id` è valorizzato → solo i punch legati a quella riga."""
    q = db.query(TimePunch).filter(
        TimePunch.job_id == job_id,
        TimePunch.end_datetime.isnot(None),
    )
    if cost_line_id is not None:
        q = q.filter(TimePunch.job_cost_line_id == cost_line_id)
    total = 0.0
    for p in q.all():
        total += (p.end_datetime - p.start_datetime).total_seconds() / 3600.0
    return round(total, 2)


def _aggregate_unassigned(db: Session, job_id: int) -> dict:
    """Ore pianificate/lavorate sul job ma NON legate a una specifica lavorazione
    (job_cost_line_id IS NULL). Utili per visualizzare un avviso "ore non assegnate"."""
    planned_q = db.query(Booking).filter(
        Booking.job_id == job_id,
        Booking.status != BookingStatus.cancelled,
        Booking.job_cost_line_id.is_(None),
    ).all()
    planned = sum(
        (b.end_datetime - b.start_datetime).total_seconds() / 3600.0
        for b in planned_q if b.start_datetime and b.end_datetime
    )
    actual_q = db.query(TimePunch).filter(
        TimePunch.job_id == job_id,
        TimePunch.end_datetime.isnot(None),
        TimePunch.job_cost_line_id.is_(None),
    ).all()
    actual = sum(
        (p.end_datetime - p.start_datetime).total_seconds() / 3600.0 for p in actual_q
    )
    return {"planned_h": round(planned, 2), "actual_h": round(actual, 2)}


def _line_dict(line: JobCostLine, db: Optional[Session] = None) -> dict:
    """Serializza una lavorazione con ore per riga (se db fornito).

    `quantity_extra` regola di calcolo:
    - is_extra=True → tutte le ore consuntivate sono extra
    - altrimenti → max(0, quantity_actual - quantity_quoted)

    Se `db` è fornito, calcola anche `planned_hours` e `actual_hours` legate a
    questa riga via `Booking.job_cost_line_id` / `TimePunch.job_cost_line_id`.
    """
    extra = 0.0
    if line.is_extra:
        extra = round(line.quantity_actual, 2)
    elif line.quantity_actual > line.quantity_quoted:
        extra = round(line.quantity_actual - line.quantity_quoted, 2)

    out = {
        "id": line.id,
        "description": line.description,
        "quote_line_id": line.quote_line_id,
        "price_item_id": line.price_item_id,
        "is_extra": line.is_extra,
        "is_billable": line.is_billable,
        "unit": line.unit,
        "unit_price": line.unit_price,
        "quantity_quoted": line.quantity_quoted,
        "quantity_actual": line.quantity_actual,
        "quantity_extra": extra,
        "total_quoted": line.total_quoted,
        "total_accrued": line.total_accrued,
        "total_expected": line.total_expected,
        "notes": line.notes,
    }
    if db is not None:
        out["planned_hours"] = _aggregate_planned_hours(db, line.job_id, line.id)
        out["actual_hours"] = _aggregate_actual_hours(db, line.job_id, line.id)
    return out


def _job_payload(db: Session, job: Job) -> dict:
    """Payload completo del job con lavorazioni + aggregazioni ore."""
    lines = sorted(job.cost_lines, key=lambda l: (l.is_extra, l.id))
    line_dicts = [_line_dict(l, db) for l in lines]

    total_quoted_h = sum(l.quantity_quoted for l in lines if not l.is_extra)
    total_actual_h = sum(l.quantity_actual for l in lines)
    total_extra_h = sum(d["quantity_extra"] for d in line_dicts)
    planned_h = _aggregate_planned_hours(db, job.id)
    actual_h = _aggregate_actual_hours(db, job.id)
    unassigned = _aggregate_unassigned(db, job.id)

    return {
        "id": job.id,
        "code": job.code,
        "title": job.title,
        "description": job.description,
        "status": job.status.value if hasattr(job.status, "value") else job.status,
        "start_date": job.start_date.isoformat() if job.start_date else None,
        "end_date": job.end_date.isoformat() if job.end_date else None,
        "budget_quoted": job.budget_quoted,
        "project": {
            "id": job.project.id,
            "code": job.project.code,
            "title": job.project.title,
        } if job.project else None,
        "client": {
            "id": job.client.id,
            "name": job.client.name,
        } if job.client else None,
        "quote": {
            "id": job.quote.id,
            "number": job.quote.number,
        } if job.quote else None,
        "cost_lines": line_dicts,
        "totals": {
            # Ore aggregate per riga (somma quantity_*)
            "quoted_hours_lines": round(total_quoted_h, 2),
            "actual_hours_lines": round(total_actual_h, 2),
            "extra_hours_lines": round(total_extra_h, 2),
            # Ore aggregate dal calendario / consuntivo (su job complessivo)
            "planned_hours_calendar": planned_h,
            "actual_hours_punch": actual_h,
            # Ore registrate sul job ma non legate a una specifica lavorazione
            "unassigned_planned_hours": unassigned["planned_h"],
            "unassigned_actual_hours": unassigned["actual_h"],
        },
    }


# ── Pagine HTML ──────────────────────────────────────────────

@router.get("/{job_id}", response_class=HTMLResponse)
async def job_detail_page(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(
            joinedload(Job.project),
            joinedload(Job.client),
            joinedload(Job.quote),
            joinedload(Job.cost_lines),
        )
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(404, "Job non trovato")

    # Lista categorie per il modal "Aggiungi lavorazione extra"
    categories = (
        db.query(PriceCategory)
        .filter(PriceCategory.tenant_id == CURRENT_TENANT)
        .order_by(PriceCategory.sort_order, PriceCategory.name)
        .all()
    )
    return _tpl().TemplateResponse(
        "pages/job_detail.html",
        {"request": request, "job": job, "categories": categories},
    )


# ── API ──────────────────────────────────────────────────────

@router.get("/api/{job_id}")
async def get_job(job_id: int, db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(
            joinedload(Job.project),
            joinedload(Job.client),
            joinedload(Job.quote),
            joinedload(Job.cost_lines),
        )
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(404, "Job non trovato")
    return _job_payload(db, job)


@router.post("/api/{job_id}/cost-lines")
async def add_cost_line(
    job_id: int,
    description: str = Form(...),
    quantity: float = Form(...),
    unit: str = Form("day"),
    unit_price: float = Form(0.0),
    notes: Optional[str] = Form(None),
    is_extra: bool = Form(True),
    is_billable: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Aggiunge una lavorazione al job. Default `is_extra=True` perché lo use case
    primario è "il cliente chiede un upres in più" dopo l'approvazione della quote.
    Per lavorazioni di scope normale si usa il flusso quote → approve → auto job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job non trovato")
    if quantity <= 0:
        raise HTTPException(400, "quantity deve essere > 0")

    total = quantity * unit_price
    line = JobCostLine(
        job_id=job.id,
        description=description.strip(),
        quantity_quoted=quantity if not is_extra else 0.0,
        quantity_actual=0.0,
        unit=unit,
        unit_price=unit_price,
        total_quoted=total if not is_extra else 0.0,
        total_expected=total,
        is_billable=is_billable,
        is_extra=is_extra,
        notes=notes,
    )
    db.add(line)
    db.commit()
    db.refresh(line)
    return _line_dict(line)


@router.put("/api/{job_id}/cost-lines/{line_id}")
async def update_cost_line(
    job_id: int,
    line_id: int,
    description: Optional[str] = Form(None),
    quantity_quoted: Optional[float] = Form(None),
    quantity_actual: Optional[float] = Form(None),
    unit: Optional[str] = Form(None),
    unit_price: Optional[float] = Form(None),
    is_extra: Optional[bool] = Form(None),
    is_billable: Optional[bool] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    line = db.query(JobCostLine).filter(
        JobCostLine.id == line_id, JobCostLine.job_id == job_id
    ).first()
    if not line:
        raise HTTPException(404, "Lavorazione non trovata")

    if description is not None: line.description = description.strip()
    if quantity_quoted is not None: line.quantity_quoted = quantity_quoted
    if quantity_actual is not None: line.quantity_actual = quantity_actual
    if unit is not None: line.unit = unit
    if unit_price is not None: line.unit_price = unit_price
    if is_extra is not None: line.is_extra = is_extra
    if is_billable is not None: line.is_billable = is_billable
    if notes is not None: line.notes = notes

    # Ricalcolo totali coerenti
    line.total_quoted = round(line.quantity_quoted * line.unit_price, 2)
    line.total_accrued = round(line.quantity_actual * line.unit_price, 2)
    line.total_expected = round(max(line.quantity_quoted, line.quantity_actual) * line.unit_price, 2)

    db.commit()
    db.refresh(line)
    return _line_dict(line)


@router.delete("/api/{job_id}/cost-lines/{line_id}")
async def delete_cost_line(job_id: int, line_id: int, db: Session = Depends(get_db)):
    line = db.query(JobCostLine).filter(
        JobCostLine.id == line_id, JobCostLine.job_id == job_id
    ).first()
    if not line:
        raise HTTPException(404, "Lavorazione non trovata")
    if not line.is_extra:
        raise HTTPException(
            400,
            "Le lavorazioni ereditate dalla quote non possono essere eliminate. "
            "Rimuovi prima la riga dalla quotazione, oppure marca questa come non fatturabile."
        )
    db.delete(line)
    db.commit()
    return {"ok": True}
