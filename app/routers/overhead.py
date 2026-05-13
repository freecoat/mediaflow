"""Router OverheadCost / Spese aziendali (v3.5.0-alpha.87 — Sprint S8).

Pozzo costi generici: costi non fatturabili al cliente che vivono nel quadro
finanziario tenant. Categorie: manutenzione, software, affitti, stipendi,
CAPEX, training, marketing, legal/admin, bank_fees, tax, other.

NB: write-off cliente NON è qui — resta in LossEntry (single source of truth).
Reportistica P&L aggrega LossEntry + OverheadCost via UNION.
"""
from __future__ import annotations

from typing import Optional
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models import (
    OverheadCost, OverheadCostCategory, RecurrenceInterval,
    Tenant, Department, Supplier, SupplierInvoice, Project,
)
from app.services.rbac import requires_permission
from app.context import current_tenant_id

router = APIRouter(prefix="/overhead", tags=["overhead"])

RequireViewOverhead = Depends(requires_permission("view_overhead"))
RequireEditOverhead = Depends(requires_permission("edit_overhead"))


def _tpl():
    from app.main import templates
    return templates


def _overhead_to_dict(o: OverheadCost) -> dict:
    return {
        "id": o.id,
        "code": o.code,
        "category": o.category.value if o.category else None,
        "title": o.title,
        "description": o.description,
        "amount_net": round(o.amount_net or 0, 2),
        "vat_rate": o.vat_rate or 22.0,
        "amount_vat": round(o.amount_vat or 0, 2),
        "amount_total": round(o.amount_total or 0, 2),
        "cost_date": str(o.cost_date) if o.cost_date else None,
        "is_recurring": o.is_recurring,
        "recurrence_interval": o.recurrence_interval.value if o.recurrence_interval else None,
        "next_due_date": str(o.next_due_date) if o.next_due_date else None,
        "is_capex": o.is_capex,
        "useful_life_months": o.useful_life_months,
        "amortization_method": o.amortization_method,
        "asset_acquisition_date": str(o.asset_acquisition_date) if o.asset_acquisition_date else None,
        "department_id": o.department_id,
        "department_name": o.department.name if o.department else None,
        "supplier_id": o.supplier_id,
        "supplier_name": o.supplier.name if o.supplier else None,
        "supplier_invoice_id": o.supplier_invoice_id,
        "booking_id": o.booking_id,
        "physical_asset_id": o.physical_asset_id,
        "source_project_id": o.source_project_id,
        "notes": o.notes,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


def _next_code(db: Session, year: int) -> str:
    """Auto-numero OH-YYYY-NNNN. Conta include_deleted per evitare collision
    con record cestinati (feedback_soft_delete_unique_bypass)."""
    prefix = f"OH-{year}-"
    n = db.query(func.count(OverheadCost.id)).filter(
        OverheadCost.tenant_id == current_tenant_id(),
        OverheadCost.code.like(prefix + "%"),
    ).scalar() or 0
    return f"{prefix}{n + 1:04d}"


# ── Pagina ───────────────────────────────────────────────────────────

@router.get("/", response_class=None)
async def overhead_page(request: Request, db: Session = Depends(get_db)):
    departments = db.query(Department).filter(
        Department.tenant_id == current_tenant_id(), Department.is_active == True
    ).all()
    return _tpl().TemplateResponse("pages/overhead.html", {
        "request": request,
        "departments": departments,
    })


# ── API ───────────────────────────────────────────────────────────────

@router.get("/api")
async def list_overhead(
    category: Optional[str] = None,
    department_id: Optional[int] = None,
    supplier_id: Optional[int] = None,
    is_capex: Optional[bool] = None,
    is_recurring: Optional[bool] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    q: Optional[str] = None,
    include_deleted: int = 0,
    db: Session = Depends(get_db),
):
    """Lista spese aziendali con filtri opzionali."""
    query = db.query(OverheadCost).options(
        joinedload(OverheadCost.department),
        joinedload(OverheadCost.supplier),
    ).filter(OverheadCost.tenant_id == current_tenant_id())
    if not include_deleted:
        query = query.filter(OverheadCost.deleted_at.is_(None))
    if category:
        try:
            query = query.filter(OverheadCost.category == OverheadCostCategory(category))
        except ValueError:
            raise HTTPException(400, f"Categoria non valida: {category}")
    if department_id:
        query = query.filter(OverheadCost.department_id == department_id)
    if supplier_id:
        query = query.filter(OverheadCost.supplier_id == supplier_id)
    if is_capex is not None:
        query = query.filter(OverheadCost.is_capex == is_capex)
    if is_recurring is not None:
        query = query.filter(OverheadCost.is_recurring == is_recurring)
    if from_date:
        query = query.filter(OverheadCost.cost_date >= from_date)
    if to_date:
        query = query.filter(OverheadCost.cost_date <= to_date)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (OverheadCost.title.ilike(like))
            | (OverheadCost.description.ilike(like))
            | (OverheadCost.code.ilike(like))
        )
    rows = query.order_by(OverheadCost.cost_date.desc()).all()
    return [_overhead_to_dict(o) for o in rows]


@router.get("/api/summary")
async def overhead_summary(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """KPI aggregato: per categoria + totale + CAPEX vs OPEX + recurring active.
    Include anche LossEntry write-off (UNION) per quadro completo costi non-billable."""
    from app.models import LossEntry
    base = db.query(OverheadCost).filter(
        OverheadCost.tenant_id == current_tenant_id(),
        OverheadCost.deleted_at.is_(None),
    )
    if from_date:
        base = base.filter(OverheadCost.cost_date >= from_date)
    if to_date:
        base = base.filter(OverheadCost.cost_date <= to_date)
    rows = base.all()
    by_category: dict[str, float] = {}
    for o in rows:
        by_category[o.category.value] = by_category.get(o.category.value, 0) + (o.amount_total or 0)
    opex_total = sum(o.amount_total or 0 for o in rows if not o.is_capex)
    capex_total = sum(o.amount_total or 0 for o in rows if o.is_capex)
    recurring_active = sum(1 for o in rows if o.is_recurring)
    # LossEntry UNION (write-off canonical source)
    loss_q = db.query(LossEntry).filter(LossEntry.tenant_id == current_tenant_id())
    if from_date:
        loss_q = loss_q.filter(LossEntry.created_at >= from_date)
    if to_date:
        from datetime import datetime as _dt, time as _time
        loss_q = loss_q.filter(LossEntry.created_at <= _dt.combine(to_date, _time.max))
    write_off_total = sum(l.amount or 0 for l in loss_q.all())
    # Includi anche write_off nel by_category per UI uniforme
    if write_off_total > 0:
        by_category["write_off"] = write_off_total
    return {
        "overhead_total":    round(opex_total + capex_total, 2),
        "opex_total":        round(opex_total, 2),
        "capex_total":       round(capex_total, 2),
        "write_off_total":   round(write_off_total, 2),
        "recurring_active":  recurring_active,
        "by_category":       {k: round(v, 2) for k, v in by_category.items()},
        "count":             len(rows),
    }


@router.post("/api", dependencies=[RequireEditOverhead])
async def create_overhead(
    category: str = Form(...),
    title: str = Form(...),
    amount_net: float = Form(...),
    cost_date: date = Form(...),
    vat_rate: float = Form(22.0),
    description: Optional[str] = Form(None),
    is_recurring: bool = Form(False),
    recurrence_interval: Optional[str] = Form(None),
    next_due_date: Optional[date] = Form(None),
    is_capex: bool = Form(False),
    useful_life_months: Optional[int] = Form(None),
    amortization_method: Optional[str] = Form(None),
    asset_acquisition_date: Optional[date] = Form(None),
    department_id: Optional[int] = Form(None),
    supplier_id: Optional[int] = Form(None),
    supplier_invoice_id: Optional[int] = Form(None),
    booking_id: Optional[int] = Form(None),
    physical_asset_id: Optional[int] = Form(None),
    source_project_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    try:
        cat_enum = OverheadCostCategory(category)
    except ValueError:
        raise HTTPException(400, f"Categoria non valida: {category}")
    ri_enum = None
    if recurrence_interval:
        try:
            ri_enum = RecurrenceInterval(recurrence_interval)
        except ValueError:
            raise HTTPException(400, f"Recurrence non valida: {recurrence_interval}")
    if is_capex and not useful_life_months:
        useful_life_months = 36  # default
        amortization_method = amortization_method or "linear"
    vat_amount = round((amount_net or 0) * (vat_rate or 0) / 100, 2)
    total = round((amount_net or 0) + vat_amount, 2)
    code = _next_code(db, cost_date.year)
    oc = OverheadCost(
        tenant_id=current_tenant_id(),
        code=code,
        category=cat_enum,
        title=title,
        description=description,
        amount_net=amount_net,
        vat_rate=vat_rate,
        amount_vat=vat_amount,
        amount_total=total,
        cost_date=cost_date,
        is_recurring=is_recurring,
        recurrence_interval=ri_enum,
        next_due_date=next_due_date,
        is_capex=is_capex,
        useful_life_months=useful_life_months,
        amortization_method=amortization_method,
        asset_acquisition_date=asset_acquisition_date,
        department_id=department_id,
        supplier_id=supplier_id,
        supplier_invoice_id=supplier_invoice_id,
        booking_id=booking_id,
        physical_asset_id=physical_asset_id,
        source_project_id=source_project_id,
        notes=notes,
    )
    db.add(oc)
    db.commit()
    db.refresh(oc)
    return _overhead_to_dict(oc)


@router.put("/api/{oc_id}", dependencies=[RequireEditOverhead])
async def update_overhead(
    oc_id: int,
    category: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    amount_net: Optional[float] = Form(None),
    vat_rate: Optional[float] = Form(None),
    cost_date: Optional[date] = Form(None),
    description: Optional[str] = Form(None),
    is_recurring: Optional[bool] = Form(None),
    recurrence_interval: Optional[str] = Form(None),
    next_due_date: Optional[date] = Form(None),
    is_capex: Optional[bool] = Form(None),
    useful_life_months: Optional[int] = Form(None),
    amortization_method: Optional[str] = Form(None),
    department_id: Optional[int] = Form(None),
    supplier_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    oc = db.query(OverheadCost).filter(
        OverheadCost.id == oc_id,
        OverheadCost.tenant_id == current_tenant_id(),
    ).first()
    if not oc:
        raise HTTPException(404, "OverheadCost non trovata")
    if category is not None:
        try:
            oc.category = OverheadCostCategory(category)
        except ValueError:
            raise HTTPException(400, f"Categoria non valida: {category}")
    if title is not None: oc.title = title
    if amount_net is not None: oc.amount_net = amount_net
    if vat_rate is not None: oc.vat_rate = vat_rate
    if amount_net is not None or vat_rate is not None:
        oc.amount_vat = round((oc.amount_net or 0) * (oc.vat_rate or 0) / 100, 2)
        oc.amount_total = round((oc.amount_net or 0) + (oc.amount_vat or 0), 2)
    if cost_date is not None: oc.cost_date = cost_date
    if description is not None: oc.description = description
    if is_recurring is not None: oc.is_recurring = is_recurring
    if recurrence_interval is not None:
        try:
            oc.recurrence_interval = RecurrenceInterval(recurrence_interval) if recurrence_interval else None
        except ValueError:
            raise HTTPException(400, f"Recurrence non valida: {recurrence_interval}")
    if next_due_date is not None: oc.next_due_date = next_due_date
    if is_capex is not None: oc.is_capex = is_capex
    if useful_life_months is not None: oc.useful_life_months = useful_life_months
    if amortization_method is not None: oc.amortization_method = amortization_method
    if department_id is not None: oc.department_id = department_id
    if supplier_id is not None: oc.supplier_id = supplier_id
    if notes is not None: oc.notes = notes
    db.commit()
    db.refresh(oc)
    return _overhead_to_dict(oc)


@router.delete("/api/{oc_id}", dependencies=[RequireEditOverhead])
async def delete_overhead(oc_id: int, db: Session = Depends(get_db)):
    oc = db.query(OverheadCost).filter(
        OverheadCost.id == oc_id,
        OverheadCost.tenant_id == current_tenant_id(),
    ).first()
    if not oc:
        raise HTTPException(404, "OverheadCost non trovata")
    oc.deleted_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "id": oc_id}


@router.get("/api/categories")
async def list_categories():
    """Espone enum categorie + label IT per popolare dropdown UI."""
    labels = {
        "maintenance":      "Manutenzione",
        "software_license": "Licenze software",
        "rent_utilities":   "Affitto / Utenze",
        "staff_overhead":   "Stipendi non-billable",
        "capex":            "Investimenti / CAPEX",
        "training":         "Formazione",
        "marketing":        "Marketing",
        "legal_admin":      "Legale / Amministrativo",
        "bank_fees":        "Commissioni bancarie",
        "tax":              "Tasse (no IVA)",
        "other":            "Altro",
    }
    return [{"value": k, "label": v} for k, v in labels.items()]
