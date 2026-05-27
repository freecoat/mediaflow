"""Bundle L Stack 1 — Router CRUD listing DeliveryVariant.

Endpoint minimali per Stack 1: list, get, create, soft-delete.
UI rich + form auto-gen da JSON Schema = Stack 4.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.variant import DeliveryVariant, DeliveryVariantCategory, VariantSchemaVersion
from app.services.rbac import requires_permission
from app.context import current_tenant_id

router = APIRouter(prefix="/delivery-variants", tags=["delivery-variants"])
templates = Jinja2Templates(directory="app/templates")


RequireEditVariants = Depends(requires_permission("edit_quotes"))  # riusa perm esistente


@router.get("/", response_class=HTMLResponse)
async def page(request: Request, db: Session = Depends(get_db)):
    variants = (
        db.query(DeliveryVariant)
        .filter(DeliveryVariant.tenant_id == current_tenant_id())
        .filter(DeliveryVariant.is_active == True)  # noqa: E712
        .order_by(DeliveryVariant.code.asc())
        .all()
    )
    return templates.TemplateResponse("pages/delivery_variants.html", {
        "request": request,
        "variants": variants,
        "categories": list(DeliveryVariantCategory),
    })


@router.get("/api/list")
async def list_variants(
    category: Optional[str] = None,
    language: Optional[str] = None,
    delivery_format: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = (
        db.query(DeliveryVariant)
        .filter(DeliveryVariant.tenant_id == current_tenant_id())
        .filter(DeliveryVariant.is_active == True)  # noqa: E712
    )
    if category:
        try:
            q = q.filter(DeliveryVariant.category == DeliveryVariantCategory(category))
        except ValueError:
            raise HTTPException(400, f"category invalida: {category}")
    if language:
        q = q.filter(DeliveryVariant.language == language)
    if delivery_format:
        q = q.filter(DeliveryVariant.delivery_format == delivery_format)
    rows = q.order_by(DeliveryVariant.code.asc()).all()
    return [{
        "id": v.id, "code": v.code, "name": v.name,
        "category": v.category.value,
        "language": v.language, "territory": v.territory,
        "delivery_format": v.delivery_format,
        "has_textless": v.has_textless, "has_subtitles": v.has_subtitles,
        "source_capitolato": v.source_capitolato,
    } for v in rows]


@router.get("/api/{variant_id}")
async def get_variant(variant_id: int, db: Session = Depends(get_db)):
    v = db.query(DeliveryVariant).filter(
        DeliveryVariant.id == variant_id,
        DeliveryVariant.tenant_id == current_tenant_id(),
    ).first()
    if not v:
        raise HTTPException(404, "Variant non trovata")
    return {
        "id": v.id, "code": v.code, "name": v.name,
        "category": v.category.value,
        "schema_version_id": v.schema_version_id,
        "spec_json": v.spec_json,
        "language": v.language, "territory": v.territory,
        "delivery_format": v.delivery_format,
        "has_textless": v.has_textless, "has_subtitles": v.has_subtitles,
        "source_capitolato": v.source_capitolato,
        "source_section": v.source_section,
        "suggested_price_item_id": v.suggested_price_item_id,
        "is_active": v.is_active,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }


@router.post("/api/create", dependencies=[RequireEditVariants])
async def create_variant(
    code: str = Form(...),
    name: str = Form(...),
    category: str = Form("t1_technical"),
    language: Optional[str] = Form(None),
    territory: Optional[str] = Form(None),
    delivery_format: Optional[str] = Form(None),
    spec_json: str = Form("{}"),
    db: Session = Depends(get_db),
):
    import json as _json
    try:
        cat = DeliveryVariantCategory(category)
    except ValueError:
        raise HTTPException(400, f"category invalida: {category}")
    try:
        spec = _json.loads(spec_json)
        if not isinstance(spec, dict):
            raise ValueError("spec_json deve essere un oggetto JSON")
    except Exception as e:
        raise HTTPException(400, f"spec_json non valido: {e}")
    sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.is_active == True).first()  # noqa: E712
    if not sv:
        raise HTTPException(500, "Nessun VariantSchemaVersion attivo")
    existing = db.query(DeliveryVariant).filter(
        DeliveryVariant.tenant_id == current_tenant_id(),
        DeliveryVariant.code == code,
    ).first()
    if existing:
        raise HTTPException(409, f"code '{code}' già usato")
    v = DeliveryVariant(
        tenant_id=current_tenant_id(),
        code=code, name=name, category=cat,
        schema_version_id=sv.id, spec_json=spec,
        language=language, territory=territory, delivery_format=delivery_format,
    )
    db.add(v); db.commit(); db.refresh(v)
    return {"ok": True, "id": v.id, "code": v.code}


@router.post("/api/{variant_id}/delete", dependencies=[RequireEditVariants])
async def soft_delete_variant(variant_id: int, db: Session = Depends(get_db)):
    v = db.query(DeliveryVariant).filter(
        DeliveryVariant.id == variant_id,
        DeliveryVariant.tenant_id == current_tenant_id(),
    ).first()
    if not v:
        raise HTTPException(404, "Variant non trovata")
    v.is_active = False
    db.commit()
    return {"ok": True}
