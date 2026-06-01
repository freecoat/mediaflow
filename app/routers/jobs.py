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
from app.services.clock import now_utc
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Job, JobStatus, JobCostLine, Booking, BookingAssignment, BookingStatus,
    TimePunch, Project, Client, PriceItem, PriceCategory,
    JobDeliverable, DeliverableNature, DeliverableStatus, QCSubstatus,
    PhysicalAsset, PhysicalAssetKind, Asset, DeliveryTemplate, Resource,
    DeliveryItem,
)
from app.context import current_tenant_id
from app.services.tenant_guard import scoped, fetch_or_404

router = APIRouter(prefix="/jobs", tags=["jobs"])


# v3.5.0-alpha.172.144 — /jobs nudo non ha lista propria (i job si gestiscono
# nel Cost Report). Redirect per evitare il 404 JSON su URL diretto/segnalibro.
@router.get("/")
async def jobs_index():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/cost-report", status_code=302)


def _tpl():
    from app.main import templates
    return templates


def _aggregate_planned_hours(db: Session, job_id: int, cost_line_id: Optional[int] = None) -> float:
    """Ore pianificate: somma di (end - start) sugli assignments dei booking attivi.
    Multi-resource v3.4.16: somma per assignment (1 booking N risorse → ore × N).
    Se `cost_line_id` è valorizzato → solo i booking legati a quella riga."""
    q = db.query(BookingAssignment).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.job_id == job_id,
        Booking.status != BookingStatus.cancelled,
    )
    if cost_line_id is not None:
        q = q.filter(Booking.job_cost_line_id == cost_line_id)
    total = 0.0
    for a in q.all():
        total += (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
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
    (job_cost_line_id IS NULL). Utili per visualizzare un avviso "ore non assegnate".
    Multi-resource v3.4.16: somma per assignment."""
    planned_q = db.query(BookingAssignment).join(Booking, BookingAssignment.booking_id == Booking.id).filter(
        Booking.job_id == job_id,
        Booking.status != BookingStatus.cancelled,
        Booking.job_cost_line_id.is_(None),
    ).all()
    planned = sum(
        (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
        for a in planned_q
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
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    job = (
        db.query(Job)
        .options(
            joinedload(Job.project),
            joinedload(Job.client),
            joinedload(Job.quote),
            joinedload(Job.cost_lines),
        )
        .filter(Job.id == job_id, Job.tenant_id == current_tenant_id())
        .first()
    )
    if not job:
        raise HTTPException(404, "Job non trovato")

    # Lista categorie per il modal "Aggiungi lavorazione extra"
    categories = (
        db.query(PriceCategory)
        .filter(PriceCategory.tenant_id == current_tenant_id())
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
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    job = (
        db.query(Job)
        .options(
            joinedload(Job.project),
            joinedload(Job.client),
            joinedload(Job.quote),
            joinedload(Job.cost_lines),
        )
        .filter(Job.id == job_id, Job.tenant_id == current_tenant_id())
        .first()
    )
    if not job:
        raise HTTPException(404, "Job non trovato")
    return _job_payload(db, job)


@router.get("/api/{job_id}/cost-lines/{line_id}/detail")
async def get_cost_line_detail(job_id: int, line_id: int, db: Session = Depends(get_db)):
    """v3.4.55 — Vista dettaglio (read-only) di una lavorazione: info + booking
    associati + risorse coinvolte + quote line di origine. Sostituisce il modal
    di edit per la maggior parte dei casi (l'edit resta accessibile a finance).
    """
    from app.models import (
        BookingAssignment, BookingExecutionStatus, BookingStatus,
        QuoteLine, Resource,
    )
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    line = scoped(db.query(JobCostLine), JobCostLine).filter(
        JobCostLine.id == line_id, JobCostLine.job_id == job_id
    ).first()
    if not line:
        raise HTTPException(404, "Lavorazione non trovata")

    # Booking attivi sulla linea + assignments + risorse
    bks = db.query(Booking).filter(
        Booking.job_cost_line_id == line.id,
        Booking.status != BookingStatus.cancelled,
    ).order_by(Booking.start_datetime.desc()).all()

    bookings_out = []
    resources_seen: dict[int, dict] = {}
    for b in bks:
        ass_out = []
        for a in b.assignments:
            r = a.resource
            if r and r.id not in resources_seen:
                resources_seen[r.id] = {
                    "id": r.id, "name": r.name,
                    "role": r.role,
                    "department_id": r.department_id,
                    "department_name": r.department.name if r.department else None,
                }
            ass_out.append({
                "id": a.id,
                "resource_id": a.resource_id,
                "resource_name": r.name if r else "?",
                "start": a.start_datetime.isoformat() if a.start_datetime else None,
                "end": a.end_datetime.isoformat() if a.end_datetime else None,
                "duration_h": round((a.end_datetime - a.start_datetime).total_seconds() / 3600.0, 2)
                              if (a.start_datetime and a.end_datetime) else 0.0,
            })
        exec_st = b.execution_status.value if hasattr(b.execution_status, "value") else str(b.execution_status)
        bookings_out.append({
            "id": b.id,
            "start": b.start_datetime.isoformat() if b.start_datetime else None,
            "end": b.end_datetime.isoformat() if b.end_datetime else None,
            "status": b.status.value if hasattr(b.status, "value") else str(b.status),
            "execution_status": exec_st,
            "notes": b.notes,
            "assignments": ass_out,
        })

    # Origine quote line
    quote_origin = None
    if line.quote_line_id:
        ql = db.query(QuoteLine).filter(QuoteLine.id == line.quote_line_id).first()
        if ql:
            quote_origin = {
                "quote_line_id": ql.id,
                "quote_id": ql.quote_id,
                "position": ql.position,
                "description": ql.description,
                "quantity": ql.quantity,
                "unit": ql.unit,
                "unit_price": ql.unit_price,
                "total": ql.total,
            }

    # v3.5.0-alpha.11: hardcost (materiali / supporti / spese vive) ereditati
    # dal price_item. La QuoteLine.hardcosts è snapshot al momento della
    # quote; lo riportiamo nel detail per visibilità nel cost report.
    hardcosts_unit = None
    hardcosts_total = None
    if quote_origin:
        from app.models import QuoteLine as _QL
        ql = db.query(_QL).filter(_QL.id == line.quote_line_id).first()
        if ql and ql.hardcosts is not None:
            hardcosts_unit = ql.hardcosts
            hardcosts_total = (ql.hardcosts or 0) * (line.quantity_quoted or 0)

    return {
        "line": {
            "id": line.id, "description": line.description,
            "is_extra": line.is_extra, "is_billable": line.is_billable,
            "unit": line.unit, "unit_price": line.unit_price,
            "quantity_quoted": line.quantity_quoted,
            "quantity_actual": line.quantity_actual,
            "total_quoted": line.total_quoted,
            "total_accrued": line.total_accrued,
            "total_expected": line.total_expected,
            "hardcosts_unit": hardcosts_unit,
            "hardcosts_total": hardcosts_total,
            "notes": line.notes,
        },
        "bookings": bookings_out,
        "resources": list(resources_seen.values()),
        "quote_origin": quote_origin,
    }


@router.post("/api/{job_id}/cost-lines")
async def add_cost_line(
    job_id: int,
    request: Request,
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
    from app.services.rbac import can_view_finance, current_user_optional
    if not can_view_finance(current_user_optional(request)):
        raise HTTPException(403, "Permesso negato (richiede view_finance)")
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    job = db.query(Job).filter(Job.id == job_id, Job.tenant_id == current_tenant_id()).first()
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
    request: Request,
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
    """v3.4.54 + v3.5.0-alpha.10 — RBAC:
    - `view_finance` per qualsiasi modifica (no producer/operator senza permesso)
    - `quantity_actual` NON è più editabile via API: è sempre sync dai booking
      marcati `done` (cost_line_sync). Decisione architetturale Matteo (4 mag):
      le ore lavorate corrispondono SEMPRE al booking; le scontistiche/banca
      ore forfait passeranno dal flusso fatturazione (in roadmap), non da qui.
      Se ricevuto un valore, restituiamo 422 invece di silently ignore così il
      client capisce che il campo è gone.
    """
    from app.services.rbac import can_view_finance, current_user_optional
    user = current_user_optional(request)
    if not can_view_finance(user):
        raise HTTPException(403, "Permesso negato (richiede view_finance)")
    if quantity_actual is not None:
        raise HTTPException(
            422,
            "Il campo 'ore lavorate' (quantity_actual) non è modificabile manualmente. "
            "Deriva sempre dai booking marcati 'done'. La fatturazione di extra/sconti "
            "passerà dal flusso fatturazione dedicato (in roadmap)."
        )

    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    line = scoped(db.query(JobCostLine), JobCostLine).filter(
        JobCostLine.id == line_id, JobCostLine.job_id == job_id
    ).first()
    if not line:
        raise HTTPException(404, "Lavorazione non trovata")

    if description is not None: line.description = description.strip()
    if quantity_quoted is not None: line.quantity_quoted = quantity_quoted
    if unit is not None: line.unit = unit
    if unit_price is not None: line.unit_price = unit_price
    if is_extra is not None: line.is_extra = is_extra
    if is_billable is not None: line.is_billable = is_billable
    if notes is not None: line.notes = notes

    # Ricalcolo totali coerenti — quantity_actual resta lock dai booking
    line.total_quoted = round(line.quantity_quoted * line.unit_price, 2)
    line.total_accrued = round(line.quantity_actual * line.unit_price, 2)
    line.total_expected = round(max(line.quantity_quoted, line.quantity_actual) * line.unit_price, 2)

    db.commit()
    db.refresh(line)
    return _line_dict(line)


@router.delete("/api/{job_id}/cost-lines/{line_id}")
async def delete_cost_line(job_id: int, line_id: int, request: Request, db: Session = Depends(get_db)):
    """v3.4.55 — HARD-BLOCK se la lavorazione ha booking attivi. Sostituisce
    il soft-detach del v3.4.36 (che rendeva il cost report incoerente).

    v3.4.54: gate view_finance.
    """
    from app.services.rbac import can_view_finance, current_user_optional
    if not can_view_finance(current_user_optional(request)):
        raise HTTPException(403, "Permesso negato (richiede view_finance)")
    # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
    line = scoped(db.query(JobCostLine), JobCostLine).filter(
        JobCostLine.id == line_id, JobCostLine.job_id == job_id
    ).first()
    if not line:
        raise HTTPException(404, "Lavorazione non trovata")
    if not line.is_extra:
        raise HTTPException(
            400,
            "Le lavorazioni ereditate dalla quote non possono essere eliminate. "
            "Rimuovi prima la riga dalla quotazione (DELETE /quotes/api/.../lines/...), "
            "oppure marca questa come non fatturabile."
        )
    # v3.4.55 — HARD-BLOCK su booking attivi
    active_bk = db.query(Booking).filter(
        Booking.job_cost_line_id == line_id,
        Booking.status != BookingStatus.cancelled,
    ).all()
    if active_bk:
        raise HTTPException(
            409,
            f"Impossibile eliminare: lavorazione collegata a {len(active_bk)} "
            f"booking attivi. Cancella o annulla prima i booking. "
            f"Booking ostativi: {[b.id for b in active_bk[:5]]}"
            + (f" e altri {len(active_bk)-5}" if len(active_bk) > 5 else "")
        )
    # TimePunch (HR, separato): soft-detach OK
    db.query(TimePunch).filter(
        TimePunch.job_cost_line_id == line_id
    ).update({"job_cost_line_id": None}, synchronize_session=False)
    db.delete(line)
    db.commit()


# ── JOB DELIVERABLES (v3.5.0-alpha.66.9) ──────────────────────
# CRUD base. UI completa (kanban, modal spec, link asset DAM, copilot QC)
# in α.66.10+.

def _serialize_deliverable(d: JobDeliverable) -> dict:
    return {
        "id": d.id,
        "job_id": d.job_id,
        "job_cost_line_id": d.job_cost_line_id,
        "price_item_id": d.price_item_id,
        "name": d.name,
        "file_naming": d.file_naming,
        "nature": d.nature.value if d.nature else "digital",
        "status": d.status.value if d.status else "planned",
        # v3.5.0-alpha.172.89 (Bundle I) — substatus QC nullable
        "qc_substatus": d.qc_substatus.value if d.qc_substatus else None,
        "delivery_template_id": d.delivery_template_id,
        # v3.5.0-alpha.172.160 (Bug B) — FK al DeliveryItem capitolato strutturato,
        # serve alla modal planning per mostrare/editare le specs con selettori taxonomy.
        "delivery_item_id": d.delivery_item_id,
        "spec_json": d.spec_json or {},
        "primary_resource_id": d.primary_resource_id,
        "estimated_hours": d.estimated_hours,
        "digital_asset_id": d.digital_asset_id,
        "physical_asset_id": d.physical_asset_id,
        "asset_locked_at": d.asset_locked_at.isoformat() + "Z" if d.asset_locked_at else None,
        "qc_report_json": d.qc_report_json,
        "qc_run_at": d.qc_run_at.isoformat() + "Z" if d.qc_run_at else None,
        "target_delivery_date": d.target_delivery_date.isoformat() if d.target_delivery_date else None,
        "delivered_date": d.delivered_date.isoformat() if d.delivered_date else None,
        "accepted_date": d.accepted_date.isoformat() if d.accepted_date else None,
        "notes": d.notes,
        "created_at": d.created_at.isoformat() + "Z" if d.created_at else None,
    }


def _compute_actual_hours(db: Session, deliverable_id: int) -> float:
    """Somma le ore di tutti i Booking attribuiti al deliverable (status != cancelled)."""
    bks = (
        db.query(Booking)
        .filter(
            Booking.job_deliverable_id == deliverable_id,
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )
    total = 0.0
    for b in bks:
        for a in (b.assignments or []):
            if a.start_datetime and a.end_datetime:
                total += (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
    return round(total, 2)


def _compute_internal_hardcost(db: Session, deliverable_id: int) -> dict:
    """Hardcost interno = somma per ogni booking di (ore × Resource.internal_cost_hourly).

    Restituisce dict con `hardcost_eur` totale e `breakdown` per risorsa.
    Solo cost report INTERNO usa questo valore — il cliente non lo vede.
    """
    bks = (
        db.query(Booking)
        .filter(
            Booking.job_deliverable_id == deliverable_id,
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )
    breakdown: dict[int, dict] = {}
    total_eur = 0.0
    for b in bks:
        for a in (b.assignments or []):
            if not (a.start_datetime and a.end_datetime):
                continue
            hours = (a.end_datetime - a.start_datetime).total_seconds() / 3600.0
            res = a.resource
            cost_h = res.internal_cost_hourly if res else None
            cost = round(hours * (cost_h or 0.0), 2)
            total_eur += cost
            slot = breakdown.setdefault(a.resource_id, {
                "resource_id": a.resource_id,
                "resource_name": res.name if res else f"#{a.resource_id}",
                "cost_type": res.cost_type.value if (res and res.cost_type) else None,
                "internal_cost_hourly": cost_h,
                "hours": 0.0, "cost_eur": 0.0,
            })
            slot["hours"] = round(slot["hours"] + hours, 2)
            slot["cost_eur"] = round(slot["cost_eur"] + cost, 2)
    return {
        "hardcost_eur": round(total_eur, 2),
        "breakdown": list(breakdown.values()),
    }


@router.get("/api/deliverables/list")
async def list_deliverables_tenant_wide(
    status: Optional[str] = None,
    qc_substatus: Optional[str] = None,
    job_id: Optional[int] = None,
    project_id: Optional[int] = None,
    include_deleted: bool = False,
    limit: int = 500,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.172.90 (Bundle J) — Lista deliverable tenant-wide per
    Planning HUB. Filtri opzionali: status, qc_substatus, job_id, project_id.
    Restituisce join Job + Project per label visualizzazione (job_code,
    job_title, project_code, project_title).

    Default: exclude deleted, limit 500 (paginazione client-side per kanban).
    """
    from sqlalchemy import or_
    q = (
        db.query(JobDeliverable, Job, Project)
        .join(Job, Job.id == JobDeliverable.job_id)
        .outerjoin(Project, Project.id == Job.project_id)
        .filter(JobDeliverable.tenant_id == current_tenant_id())
    )
    if not include_deleted:
        q = q.filter(JobDeliverable.deleted_at.is_(None))
        # v3.5.0-alpha.172.160 (Bug A) — escludi deliverable di progetti cestinati
        # (soft-delete). outerjoin: tieni le righe senza progetto (project NULL).
        q = q.filter(or_(Project.id.is_(None), Project.deleted_at.is_(None)))
    if status:
        try:
            q = q.filter(JobDeliverable.status == DeliverableStatus(status))
        except ValueError:
            raise HTTPException(400, f"status invalido: {status}")
    if qc_substatus:
        try:
            q = q.filter(JobDeliverable.qc_substatus == QCSubstatus(qc_substatus))
        except ValueError:
            raise HTTPException(400, f"qc_substatus invalido: {qc_substatus}")
    if job_id:
        q = q.filter(JobDeliverable.job_id == job_id)
    if project_id:
        q = q.filter(Job.project_id == project_id)

    rows = q.order_by(
        JobDeliverable.target_delivery_date.asc().nullslast(),
        JobDeliverable.id.asc(),
    ).limit(limit).all()

    out = []
    for d, j, p in rows:
        rec = _serialize_deliverable(d)
        rec["job_id"] = j.id
        rec["job_code"] = j.code
        rec["job_title"] = j.title
        rec["project_id"] = p.id if p else None
        rec["project_code"] = p.code if p else None
        rec["project_title"] = p.title if p else None
        out.append(rec)
    return {"count": len(out), "items": out}


@router.get("/api/{job_id}/deliverables")
async def list_deliverables(
    job_id: int,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    job = db.query(Job).filter(Job.id == job_id, Job.tenant_id == current_tenant_id()).first()
    if not job:
        raise HTTPException(404, "Job non trovato")
    q = db.query(JobDeliverable).filter(
        JobDeliverable.job_id == job_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    )
    if not include_deleted:
        q = q.filter(JobDeliverable.deleted_at.is_(None))
    items = q.order_by(JobDeliverable.target_delivery_date.asc(), JobDeliverable.id.asc()).all()
    out = []
    for d in items:
        rec = _serialize_deliverable(d)
        rec["actual_hours"] = _compute_actual_hours(db, d.id)
        out.append(rec)
    return out


@router.post("/api/{job_id}/deliverables")
async def create_deliverable(
    job_id: int,
    request: Request,
    name: str = Form(...),
    nature: str = Form("digital"),
    job_cost_line_id: Optional[int] = Form(None),
    price_item_id: Optional[int] = Form(None),
    delivery_template_id: Optional[int] = Form(None),
    delivery_item_id: Optional[int] = Form(None),  # v3.5.0-alpha.172.115 Tier 2.5
    primary_resource_id: Optional[int] = Form(None),
    estimated_hours: Optional[float] = Form(None),
    target_delivery_date: Optional[str] = Form(None),
    file_naming: Optional[str] = Form(None),
    spec_json: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    quantity: int = Form(1, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Crea N JobDeliverable (default 1, max 50) per un job.

    Quando quantity > 1 (es. quote.line.quantity=3 DCP per 3 territori) crea
    N deliverable separati con suffix "(1/N)", "(2/N)" sul nome — l'utente
    li distingue poi nei dettagli (territorio/spec/QC).
    """
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    # Permesso: usiamo edit_planning_all (chi può creare booking può creare deliverable).
    if not has_permission(user, "edit_planning_all") and not has_permission(user, "assign_resources"):
        raise HTTPException(403, "Permesso insufficiente per creare deliverable")

    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    job = db.query(Job).filter(Job.id == job_id, Job.tenant_id == current_tenant_id()).first()
    if not job:
        raise HTTPException(404, "Job non trovato")

    try:
        nature_enum = DeliverableNature(nature)
    except ValueError:
        raise HTTPException(400, f"nature invalida: {nature}")

    # Parsing spec_json se fornito come stringa
    spec_dict: Optional[dict] = None
    if spec_json:
        try:
            import json as _json
            spec_dict = _json.loads(spec_json)
            if not isinstance(spec_dict, dict):
                raise ValueError("spec_json deve essere un oggetto JSON")
        except Exception as e:
            raise HTTPException(400, f"spec_json non valido: {e}")

    # F3.1 — auto-snapshot: se è collegato un DeliveryItem e non è stato passato
    # uno spec_json esplicito, congela le specs del capitolato nel deliverable
    # (decoupling da edit successivi). L'item deve appartenere al tenant.
    if spec_dict is None and delivery_item_id:
        from app.services.delivery_snapshot import snapshot_delivery_item
        di = db.query(DeliveryItem).filter(
            DeliveryItem.id == delivery_item_id,
            DeliveryItem.tenant_id == current_tenant_id(),
        ).first()
        if di:
            spec_dict = snapshot_delivery_item(db, di)

    # Parsing target_delivery_date
    target_d = None
    if target_delivery_date:
        try:
            target_d = datetime.strptime(target_delivery_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "target_delivery_date deve essere YYYY-MM-DD")

    created = []
    for i in range(quantity):
        suffix = f" ({i+1}/{quantity})" if quantity > 1 else ""
        d = JobDeliverable(
            tenant_id=current_tenant_id(),
            job_id=job_id,
            job_cost_line_id=job_cost_line_id,
            price_item_id=price_item_id,
            name=name.strip()[:255] + suffix,
            nature=nature_enum,
            status=DeliverableStatus.planned,
            delivery_template_id=delivery_template_id,
            delivery_item_id=delivery_item_id,
            primary_resource_id=primary_resource_id,
            estimated_hours=estimated_hours,
            target_delivery_date=target_d,
            file_naming=(file_naming or "").strip()[:500] or None,
            spec_json=spec_dict,
            notes=(notes or "").strip() or None,
        )
        db.add(d); db.flush()
        created.append(d)
    db.commit()
    return {
        "ok": True,
        "created": len(created),
        "deliverables": [_serialize_deliverable(d) for d in created],
    }


@router.get("/api/deliverables/{deliverable_id}")
async def get_deliverable(deliverable_id: int, db: Session = Depends(get_db)):
    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    rec = _serialize_deliverable(d)
    rec["actual_hours"] = _compute_actual_hours(db, d.id)
    rec["internal_hardcost"] = _compute_internal_hardcost(db, d.id)
    return rec


@router.post("/api/deliverables/{deliverable_id}/qc-compare")
async def qc_compare_deliverable(deliverable_id: int, db: Session = Depends(get_db)):
    """F3.3 — confronta on-demand le specs reali dell'asset digitale linkato con
    quelle attese del capitolato (DeliveryItem). Salva in qc_report_json."""
    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    if not d.delivery_item_id:
        raise HTTPException(400, "Deliverable non collegato a un capitolato (delivery_item)")
    if not d.digital_asset_id:
        raise HTTPException(400, "Nessun asset digitale linkato al deliverable")
    from app.services.qc_specs_compare import run_deliverable_qc_compare
    report = run_deliverable_qc_compare(db, d)
    if report is None:
        raise HTTPException(400, "Asset linkato senza tech_specs estratte (esegui prima l'estrazione)")
    db.commit()
    return {"ok": True, "qc_report": report}


@router.put("/api/deliverables/{deliverable_id}")
async def update_deliverable(
    deliverable_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    nature: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    qc_substatus: Optional[str] = Form(None),
    qc_reject_reason: Optional[str] = Form(None),
    job_cost_line_id: Optional[int] = Form(None),
    price_item_id: Optional[int] = Form(None),
    delivery_template_id: Optional[int] = Form(None),
    # α.172.161 — link item capitolato. str (non int) per distinguere "" (unlink
    # esplicito → NULL) da assente (None → no-op). Optional[int]+"" verrebbe
    # coerciato a None da FastAPI, rendendo impossibile lo scollegamento.
    delivery_item_id: Optional[str] = Form(None),
    primary_resource_id: Optional[int] = Form(None),
    estimated_hours: Optional[float] = Form(None),
    target_delivery_date: Optional[str] = Form(None),
    delivered_date: Optional[str] = Form(None),
    accepted_date: Optional[str] = Form(None),
    file_naming: Optional[str] = Form(None),
    spec_json: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    digital_asset_id: Optional[int] = Form(None),
    physical_asset_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_planning_all") and not has_permission(user, "assign_resources"):
        raise HTTPException(403, "Permesso insufficiente")

    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")

    # v3.5.0-alpha.172.89 (Bundle I) — closed e' irreversibile.
    # Permettiamo solo no-op (status uguale) o nessun cambio status.
    if d.status == DeliverableStatus.closed and status is not None and status != "closed":
        raise HTTPException(
            409,
            f"Deliverable in stato 'closed' immutabile. "
            f"Status non puo' essere riaperto via update (transizione richiede storno formale)."
        )

    if name is not None:
        d.name = name.strip()[:255] or d.name
    if nature is not None:
        try: d.nature = DeliverableNature(nature)
        except ValueError: raise HTTPException(400, f"nature invalida: {nature}")

    # v3.5.0-alpha.172.89 (Bundle I) — Stati nested. Validazione + cascade.
    # v3.5.0-alpha.172.98 (Bundle L Stack 2) — QC transitions ora delegano a
    # `app.services.qc_events` (event-sourced). Il listener after_insert su
    # QCEvent sincronizza d.qc_substatus + d.qc_run_at + d.qc_run_by_user_id
    # per back-compat con UI Bundle I. La cascade reject e' chiamata qui per
    # preservare il workflow esistente (asset rejected + spawn placeholder).
    triggered_qc_cascade = None
    if status is not None:
        try:
            new_status = DeliverableStatus(status)
        except ValueError:
            raise HTTPException(400, f"status invalido: {status}")
        # qc_substatus valido solo se main==qc
        new_sub: Optional[QCSubstatus] = None
        if qc_substatus is not None and qc_substatus != "":
            if new_status != DeliverableStatus.qc:
                raise HTTPException(400, "qc_substatus ammesso solo con status='qc'")
            try:
                new_sub = QCSubstatus(qc_substatus)
            except ValueError:
                raise HTTPException(400, f"qc_substatus invalido: {qc_substatus}")

        # Path A: main status NON qc -> mutazione diretta legacy (nessun QC event)
        if new_status != DeliverableStatus.qc:
            d.status = new_status
            d.qc_substatus = None
            if new_status == DeliverableStatus.delivered and not d.delivered_date:
                d.delivered_date = date.today()
        else:
            # Path B: main status = qc -> delega allo stream QCEvent.
            from app.services import qc_events as _qc
            from app.services.qc_event_listener import rebuild_qc_report
            actor_id = user.id if user else None

            # Apri un QC round se ancora non esiste oppure se l'ultimo era
            # gia' terminato (passed/failed/conditional) e ora si vuole
            # ricominciare → in entrambi i casi: chiama start_qc().
            from app.models import QCReport as _QCReport
            cur_rep = db.query(_QCReport).filter(
                _QCReport.deliverable_id == d.id
            ).first()
            need_start = (cur_rep is None) or (
                cur_rep.overall_status not in ("in_progress", "reopened")
            )
            if need_start:
                _qc.start_qc(db, d.id, operator_id=actor_id, source="bundle_i_update")

            # Mappa substatus -> event emit
            if new_sub == QCSubstatus.passed:
                _qc.pass_qc(db, d.id, operator_id=actor_id, source="bundle_i_update")
            elif new_sub == QCSubstatus.rejected:
                _qc.fail_qc(
                    db, d.id,
                    primary_cause=qc_reject_reason or "QC rejected via Bundle I update",
                    operator_id=actor_id,
                    source="bundle_i_update",
                )
            # qc_substatus=in_progress o None: stato di attesa, nessun event
            # terminal richiesto (qc_started gia' emesso sopra se needed).

            # Listener after_insert ha sincronizzato d.status + d.qc_substatus.
            # Per sicurezza forza re-read da DB.
            db.flush()

        # Cascade QC reject (richiesta Bundle I, indipendente dal path event-sourced)
        if new_status == DeliverableStatus.qc and new_sub == QCSubstatus.rejected:
            from app.services.qc_cascade import cascade_qc_reject
            triggered_qc_cascade = cascade_qc_reject(
                db, d,
                actor_user_id=user.id if user else None,
                reason=qc_reject_reason,
            )
    if job_cost_line_id is not None: d.job_cost_line_id = job_cost_line_id or None
    if price_item_id is not None: d.price_item_id = price_item_id or None
    if delivery_template_id is not None: d.delivery_template_id = delivery_template_id or None
    # α.172.161 — link/unlink al DeliveryItem capitolato (punto-di-partenza specs).
    # "" → scollega (NULL). id valido → verifica esistenza+tenant. None → no-op.
    if delivery_item_id is not None:
        raw = delivery_item_id.strip()
        if raw in ("", "0"):
            d.delivery_item_id = None
        else:
            try:
                iid = int(raw)
            except ValueError:
                raise HTTPException(400, f"delivery_item_id non valido: {raw}")
            it = db.query(DeliveryItem).filter(
                DeliveryItem.id == iid,
                DeliveryItem.tenant_id == current_tenant_id(),
            ).first()
            if not it:
                raise HTTPException(404, "DeliveryItem non trovato")
            d.delivery_item_id = it.id
    if primary_resource_id is not None: d.primary_resource_id = primary_resource_id or None
    if estimated_hours is not None: d.estimated_hours = estimated_hours
    if file_naming is not None: d.file_naming = file_naming.strip()[:500] or None
    if notes is not None: d.notes = notes.strip() or None

    if target_delivery_date is not None:
        d.target_delivery_date = datetime.strptime(target_delivery_date, "%Y-%m-%d").date() if target_delivery_date else None
    if delivered_date is not None:
        d.delivered_date = datetime.strptime(delivered_date, "%Y-%m-%d").date() if delivered_date else None
    if accepted_date is not None:
        d.accepted_date = datetime.strptime(accepted_date, "%Y-%m-%d").date() if accepted_date else None

    if spec_json is not None:
        try:
            import json as _json
            d.spec_json = _json.loads(spec_json) if spec_json else None
        except Exception as e:
            raise HTTPException(400, f"spec_json non valido: {e}")

    # Bridge asset (mutually exclusive con nature)
    # v3.5.0-alpha.172.89 (Bundle I): rimosso auto-bump in_production→file_attached
    # (enum collassato). Link asset NON cambia status main; cambio esplicito via UI.
    if digital_asset_id is not None:
        d.digital_asset_id = digital_asset_id or None
        if digital_asset_id:
            d.asset_locked_at = now_utc()
    if physical_asset_id is not None:
        d.physical_asset_id = physical_asset_id or None
        if physical_asset_id:
            d.asset_locked_at = now_utc()

    db.commit()
    payload = _serialize_deliverable(d)
    if triggered_qc_cascade:
        payload["qc_cascade"] = triggered_qc_cascade
    return payload


@router.post("/api/deliverables/{deliverable_id}/close")
async def close_deliverable(
    deliverable_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.172.89 (Bundle I) — Chiusura formale deliverable.
    Solo transizione consentita: delivered -> closed. Irreversibile.
    Permesso: view_finance (atto formale finance-level).
    """
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "view_finance"):
        raise HTTPException(403, "Permesso insufficiente (richiesto view_finance)")
    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    if d.status != DeliverableStatus.delivered:
        raise HTTPException(
            409,
            f"Solo deliverable in stato 'delivered' chiudibili (attuale: {d.status.value})."
        )
    d.status = DeliverableStatus.closed
    d.qc_substatus = None
    db.commit()
    return _serialize_deliverable(d)


@router.delete("/api/deliverables/{deliverable_id}")
async def delete_deliverable(
    deliverable_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Soft-delete del deliverable. Booking attribuiti restano (job_deliverable_id resta).
    Per recuperare: PATCH /api/deliverables/{id}/restore."""
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_planning_all") and not has_permission(user, "assign_resources"):
        raise HTTPException(403, "Permesso insufficiente")
    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    d.deleted_at = now_utc()
    db.commit()
    return {"ok": True, "id": deliverable_id}


@router.post("/api/deliverables/{deliverable_id}/restore")
async def restore_deliverable(
    deliverable_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not has_permission(user, "edit_planning_all") and not has_permission(user, "assign_resources"):
        raise HTTPException(403, "Permesso insufficiente")
    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).execution_options(include_deleted=True).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    d.deleted_at = None
    db.commit()
    return _serialize_deliverable(d)


# ─────────────────────────────────────────────────────────────
# v3.5.0-alpha.172.3 Restructure Sprint 3 — Confirm delivery workflow
# Producer/manager conferma `quantity_delivered` per deliverable, opzionale
# link a un asset (digital o physical) come verifica.
# ─────────────────────────────────────────────────────────────

@router.post("/api/deliverables/{deliverable_id}/confirm-delivery")
async def confirm_deliverable_delivery(
    deliverable_id: int,
    request: Request,
    quantity: float = Form(1.0),
    asset_id: Optional[int] = Form(None),
    physical_asset_id: Optional[int] = Form(None),
    source: str = Form("manual"),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Conferma consegna di N unita' del deliverable (default 1).

    Effetti:
    - quantity_delivered += quantity (max = quantity_planned)
    - status -> delivered se quantity_delivered >= quantity_planned
    - confirmed_at + confirmed_by_user_id popolati al primo delivery
    - opzionale: crea row in deliverable_assets per verifica (XOR asset_id |
      physical_asset_id)
    - source: manual | mhl_yoyotta | csv_lto | fs_scan | ai_proposal
    - emette warning se booking ore=0 sui pivot (decision 8 punto B
      RESTRUCTURE_2026_05_20.md: maturato senza ore = WARN, non blocco)
    """
    from app.services.rbac import current_user_optional, has_permission
    from app.models import DeliverableAsset, BookingDeliverable, Booking
    from sqlalchemy import func

    user = current_user_optional(request)
    if not has_permission(user, "confirm_deliverables"):
        raise HTTPException(403, "Permesso insufficiente per confermare consegne")

    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    if d.deleted_at is not None:
        raise HTTPException(400, "Deliverable in cestino, ripristina prima di confermare")

    if quantity <= 0:
        raise HTTPException(400, "quantity deve essere > 0")

    if asset_id is not None and physical_asset_id is not None:
        raise HTTPException(400, "asset_id e physical_asset_id mutualmente esclusivi")

    valid_sources = {"manual", "mhl_yoyotta", "csv_lto", "fs_scan", "ai_proposal"}
    if source not in valid_sources:
        raise HTTPException(400, f"source invalido. Valid: {sorted(valid_sources)}")

    new_qty = (d.quantity_delivered or 0.0) + quantity
    planned = d.quantity_planned or 0.0
    if planned and new_qty > planned + 1e-6:
        raise HTTPException(
            400,
            f"quantity_delivered ({new_qty}) supera quantity_planned ({planned}). "
            "Riduci o aggiorna quantity_planned."
        )

    # First-time confirmation: popola audit
    if (d.quantity_delivered or 0) <= 0 and d.confirmed_at is None:
        d.confirmed_at = now_utc()
        d.confirmed_by_user_id = user.id if user else None

    d.quantity_delivered = new_qty
    # Update status
    if new_qty >= planned > 0:
        d.status = DeliverableStatus.delivered
        d.delivered_date = now_utc().date()
    elif new_qty > 0:
        d.status = DeliverableStatus.in_progress

    # Recompute revenue + cost (cost da deliverable_cost_sync se booking linked)
    from app.services.deliverable_cost_sync import recompute_deliverable_cost
    recompute_deliverable_cost(db, d)

    # Warning: maturato confermato ma zero ore tracked sui booking linked
    n_link_bookings_with_hours = db.query(func.count(BookingDeliverable.id)).filter(
        BookingDeliverable.job_deliverable_id == d.id
    ).scalar() or 0
    if n_link_bookings_with_hours == 0:
        try:
            from app.services.notifications import notify_permission, NotificationKind, NotificationSeverity
            notify_permission(
                db,
                permission="view_finance",
                kind="deliverable_confirmed_no_hours",
                severity="info",
                title=f"Consegna confermata senza ore tracciate — {d.name[:60]}",
                body=(
                    f"Deliverable '{d.name}' confermato come consegnato "
                    f"({d.quantity_delivered}/{d.quantity_planned} {d.unit}) "
                    f"ma nessun booking linkato: maturato confermato senza ore di lavorazione. "
                    "Verifica se le ore vanno tracciate."
                ),
                link=f"/jobs/{d.job_id}",
                payload={
                    "deliverable_id": d.id,
                    "job_id": d.job_id,
                    "quantity_delivered": d.quantity_delivered,
                },
                actor_user_id=user.id if user else None,
            )
        except Exception as _e:
            pass  # notifica non bloccante

    # Optional asset link
    asset_link_created = None
    if asset_id is not None or physical_asset_id is not None:
        link = DeliverableAsset(
            job_deliverable_id=d.id,
            asset_id=asset_id,
            physical_asset_id=physical_asset_id,
            source=source,
            confirmed_by_user_id=user.id if user else None,
            notes=notes,
        )
        db.add(link); db.flush()
        asset_link_created = link.id
        # Sync FK legacy primary se vuoto
        if asset_id and not d.digital_asset_id:
            d.digital_asset_id = asset_id
        if physical_asset_id and not d.physical_asset_id:
            d.physical_asset_id = physical_asset_id

    # F3.3 lazy bridge — al link di un asset digitale con tech_specs, confronta
    # le specs reali con quelle attese del capitolato (non bloccante).
    qc_compare = None
    if d.digital_asset_id and d.delivery_item_id:
        try:
            from app.services.qc_specs_compare import run_deliverable_qc_compare
            qc_compare = run_deliverable_qc_compare(db, d)
        except Exception:
            pass  # confronto best-effort, non blocca la conferma

    db.commit()
    db.refresh(d)

    return {
        "ok": True,
        "deliverable_id": d.id,
        "quantity_delivered": d.quantity_delivered,
        "quantity_planned": d.quantity_planned,
        "status": d.status.value,
        "total_accrued": d.total_accrued,
        "total_cost_accrued": d.total_cost_accrued,
        "confirmed_at": d.confirmed_at.isoformat() if d.confirmed_at else None,
        "asset_link_id": asset_link_created,
        "warn_no_hours": n_link_bookings_with_hours == 0,
        "qc_compare": qc_compare,
    }


# ─────────────────────────────────────────────────────────────
# v3.5.0-alpha.172.89 (Bundle I) — Upload QC report multipli (PDF).
# Crea Asset standalone + DeliverableAsset(source='qc_report') linkato.
# Trigger opzionale capability AI propose_qc_report_summary post-upload.
# ─────────────────────────────────────────────────────────────

@router.post("/api/deliverables/{deliverable_id}/qc-report")
async def upload_qc_report(
    deliverable_id: int,
    request: Request,
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    from app.services.rbac import current_user_optional, has_permission
    from app.services.dam import save_upload, resolve_asset_type
    from app.models import DeliverableAsset, AssetStatus

    user = current_user_optional(request)
    if not has_permission(user, "edit_planning_all") and not has_permission(user, "assign_resources"):
        raise HTTPException(403, "Permesso insufficiente")

    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")

    if file.size and file.size > 50 * 1024 * 1024:
        raise HTTPException(413, "QC report troppo grande (max 50 MB)")

    file_bytes = await file.read()
    filename, file_path, mime_type = save_upload(file_bytes, file.filename)
    asset_type = resolve_asset_type(mime_type)

    qc_asset = Asset(
        tenant_id=d.tenant_id,
        filename=filename,
        original_name=file.filename,
        file_path=file_path,
        asset_type=asset_type,
        mime_type=mime_type,
        file_size=len(file_bytes),
        job_id=d.job_id,
        uploaded_by=user.id if user else 1,
        description=f"QC report deliverable #{d.id} — {d.name[:80]}",
        status=AssetStatus.uploaded,
    )
    db.add(qc_asset); db.flush()

    link = DeliverableAsset(
        job_deliverable_id=d.id,
        asset_id=qc_asset.id,
        source="qc_report",
        confirmed_by_user_id=user.id if user else None,
        notes=(notes or "").strip() or None,
    )
    db.add(link); db.flush()

    db.commit()
    return {
        "ok": True,
        "deliverable_id": d.id,
        "qc_asset_id": qc_asset.id,
        "deliverable_asset_id": link.id,
        "filename": filename,
        "mime_type": mime_type,
    }


# ── NAMING HELPER (v3.5.0-alpha.66.9) ────────────────────────

@router.get("/api/naming/presets")
async def list_naming_presets():
    """Lista preset di template naming (ISDCF, Netflix, broadcast, ecc.)."""
    from app.services.naming_helper import PRESET_TEMPLATES, TOKEN_HELP
    return {"presets": PRESET_TEMPLATES, "tokens": TOKEN_HELP}


@router.post("/api/naming/preview")
async def preview_naming(
    template: str = Form(...),
    deliverable_id: Optional[int] = Form(None),
    overrides_json: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Risolve un template di naming dati i token del contesto + overrides.
    Output: nome file generato + lista token ancora mancanti.
    """
    from app.services.naming_helper import build_token_dict, resolve_template
    import json as _json

    overrides = {}
    if overrides_json:
        try:
            overrides = _json.loads(overrides_json) or {}
            if not isinstance(overrides, dict):
                raise ValueError("overrides_json deve essere un oggetto")
        except Exception as e:
            raise HTTPException(400, f"overrides_json non valido: {e}")

    deliverable = None
    job = None
    if deliverable_id:
        deliverable = db.query(JobDeliverable).filter(
            JobDeliverable.id == deliverable_id,
            JobDeliverable.tenant_id == current_tenant_id(),
        ).first()
        if deliverable:
            # v3.5.0-alpha.172.35 (Sprint 1) — tenant guard
            job = scoped(db.query(Job), Job).filter(Job.id == deliverable.job_id).first()

    tokens = build_token_dict(
        db, deliverable=deliverable, job=job, overrides=overrides,
    )
    output, missing = resolve_template(template, tokens)
    return {
        "output": output,
        "missing_tokens": missing,
        "resolved_tokens": tokens,
    }

    return {"ok": True}
