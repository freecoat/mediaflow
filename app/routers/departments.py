"""
Router reparti (Department) — Fase 1-bis.

Ogni risorsa e voce listino appartiene a un reparto. I reparti sono
trasversali e definiscono la responsabilità finanziaria. Default:
DI-Video, VFX, Audio, Commercial.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import Department, Resource, PriceItem

router = APIRouter(prefix="/departments", tags=["departments"])

# Tenant corrente: in Fase 1-bis sempre 1 (multi-tenant soft).
CURRENT_TENANT = 1


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def departments_page(request: Request, db: Session = Depends(get_db)):
    depts = (
        db.query(Department)
        .filter(Department.tenant_id == CURRENT_TENANT)
        .order_by(Department.sort_order, Department.name)
        .all()
    )
    # Calcolo conteggi per ogni reparto
    for d in depts:
        d._resources_count = (
            db.query(Resource)
            .filter(Resource.department_id == d.id, Resource.is_active == True)
            .count()
        )
        d._price_items_count = (
            db.query(PriceItem)
            .filter(PriceItem.department_id == d.id, PriceItem.is_active == True)
            .count()
        )
    return _tpl().TemplateResponse(
        "pages/departments.html",
        {"request": request, "departments": depts}
    )


# ── API JSON ─────────────────────────────────────────────────

@router.get("/api")
async def list_departments(db: Session = Depends(get_db)):
    depts = (
        db.query(Department)
        .filter(Department.tenant_id == CURRENT_TENANT)
        .order_by(Department.sort_order, Department.name)
        .all()
    )
    return [
        {
            "id": d.id,
            "code": d.code,
            "name": d.name,
            "description": d.description,
            "color": d.color,
            "sort_order": d.sort_order,
            "annual_budget": d.annual_budget,
            "is_active": d.is_active,
            "resources_count": db.query(Resource).filter(
                Resource.department_id == d.id, Resource.is_active == True
            ).count(),
            "price_items_count": db.query(PriceItem).filter(
                PriceItem.department_id == d.id, PriceItem.is_active == True
            ).count(),
        }
        for d in depts
    ]


@router.post("/api")
async def create_department(
    code: str = Form(...),
    name: str = Form(...),
    color: str = Form("#6272f5"),
    description: Optional[str] = Form(None),
    sort_order: int = Form(0),
    annual_budget: Optional[float] = Form(None),
    db: Session = Depends(get_db),
):
    code = code.strip().upper()
    if not code or not name:
        raise HTTPException(400, "Codice e nome obbligatori")

    existing = db.query(Department).filter(
        Department.tenant_id == CURRENT_TENANT,
        Department.code == code
    ).first()
    if existing:
        raise HTTPException(400, f"Esiste già un reparto con codice {code}")

    d = Department(
        tenant_id=CURRENT_TENANT,
        code=code, name=name.strip(),
        color=color, description=description,
        sort_order=sort_order,
        annual_budget=annual_budget,
    )
    db.add(d)
    try:
        db.commit()
        db.refresh(d)
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Errore creazione reparto (codice duplicato?)")
    return {"id": d.id, "code": d.code, "name": d.name}


@router.put("/api/{dept_id}")
async def update_department(
    dept_id: int,
    name: Optional[str] = Form(None),
    color: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    annual_budget: Optional[float] = Form(None),
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    d = db.query(Department).filter(
        Department.id == dept_id,
        Department.tenant_id == CURRENT_TENANT
    ).first()
    if not d:
        raise HTTPException(404, "Reparto non trovato")

    if name is not None: d.name = name.strip()
    if color is not None: d.color = color
    if description is not None: d.description = description
    if sort_order is not None: d.sort_order = sort_order
    if annual_budget is not None: d.annual_budget = annual_budget
    if is_active is not None: d.is_active = is_active

    db.commit()
    return {"ok": True, "id": d.id}


@router.delete("/api/{dept_id}")
async def delete_department(dept_id: int, db: Session = Depends(get_db)):
    d = db.query(Department).filter(
        Department.id == dept_id,
        Department.tenant_id == CURRENT_TENANT
    ).first()
    if not d:
        raise HTTPException(404, "Reparto non trovato")

    # Controllo se ci sono risorse o voci listino collegate
    resources_count = db.query(Resource).filter(Resource.department_id == d.id).count()
    items_count = db.query(PriceItem).filter(PriceItem.department_id == d.id).count()

    if resources_count or items_count:
        raise HTTPException(
            400,
            f"Impossibile eliminare: {resources_count} risorse e {items_count} voci listino collegate. "
            "Riassegna le risorse a un altro reparto prima di eliminare."
        )

    db.delete(d)
    db.commit()
    return {"ok": True}
