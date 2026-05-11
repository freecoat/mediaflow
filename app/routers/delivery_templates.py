"""Router DeliveryTemplate — gestione capitolati consegna (8 blocchi JSON).

v3.5.0-alpha.66.20 Fase 2 step C — Cabla `deliverables_parser.parse_delivery_template`
in una pagina dedicata `/delivery-templates`.

Flow F14:
  1. Upload PDF/docx/xlsx → POST /api/parse
  2. Preview AI-extracted 8 blocchi → utente corregge
  3. POST /api/save → INSERT DeliveryTemplate
  4. Lista / edit / delete da pagina HTML.

Permessi: lettura libera, mutator richiedono `edit_settings`.
"""
from __future__ import annotations
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import DeliveryTemplate
from app.services.rbac import requires_permission

router = APIRouter(prefix="/delivery-templates", tags=["delivery-templates"])

CURRENT_TENANT = 1
RequireEditSettings = Depends(requires_permission("edit_settings"))


def _tpl():
    from app.main import templates
    return templates


def _dt_dict(t: DeliveryTemplate) -> dict:
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "broadcaster": t.broadcaster,
        "version": t.version,
        "description": t.description,
        "video_specs": t.video_specs or {},
        "audio_specs": t.audio_specs or {},
        "text_specs": t.text_specs or {},
        "head_format": t.head_format or {},
        "textless_format": t.textless_format or {},
        "naming_convention": t.naming_convention or {},
        "archive_specs": t.archive_specs or {},
        "metadata_requirements": t.metadata_requirements or {},
        "suggested_items": t.suggested_items or [],
        "source_document_name": t.source_document_name,
        "ai_generated": t.ai_generated,
        "ai_confidence": t.ai_confidence,
        "is_active": t.is_active,
        "created_at": str(t.created_at)[:19] if t.created_at else None,
    }


# ── Pagina HTML ───────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
async def delivery_templates_page(request: Request, db: Session = Depends(get_db)):
    templates = (
        db.query(DeliveryTemplate)
        .filter(DeliveryTemplate.tenant_id == CURRENT_TENANT)
        .order_by(DeliveryTemplate.broadcaster.asc(), DeliveryTemplate.name.asc())
        .all()
    )
    return _tpl().TemplateResponse(
        "pages/delivery_templates.html",
        {"request": request, "templates": templates},
    )


# ── API ───────────────────────────────────────────────────────────────


@router.get("/api/list")
async def list_templates(db: Session = Depends(get_db)):
    rows = (
        db.query(DeliveryTemplate)
        .filter(DeliveryTemplate.tenant_id == CURRENT_TENANT)
        .order_by(DeliveryTemplate.broadcaster.asc(), DeliveryTemplate.name.asc())
        .all()
    )
    return [_dt_dict(t) for t in rows]


@router.get("/api/{template_id}")
async def get_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == CURRENT_TENANT,
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")
    return _dt_dict(t)


@router.post("/api/parse", dependencies=[RequireEditSettings])
async def parse_capitolato(file: UploadFile = File(...)):
    """Estrae da un capitolato (PDF/docx/xlsx/txt) gli 8 blocchi DeliveryTemplate
    via AI. Read-only: ritorna la preview JSON, NON salva.

    Frontend usa il payload per popolare il modal di preview e permettere
    correzioni manuali prima del POST /api/save.
    """
    from app.services.deliverables_parser import (
        extract_text_from_file, parse_delivery_template,
    )

    if not file.filename:
        raise HTTPException(400, "Nome file mancante")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "File vuoto")
    text = extract_text_from_file(file_bytes, file.filename)
    if not text or len(text.strip()) < 20:
        raise HTTPException(400, "Estrazione testo fallita o testo troppo breve (<20 caratteri)")
    parsed = parse_delivery_template(text)
    if parsed is None:
        raise HTTPException(503, "Provider AI non disponibile o estrazione fallita. Configura un provider in /settings → AI.")
    parsed.setdefault("source_document_name", file.filename)
    parsed.setdefault("ai_generated", True)
    parsed.setdefault("text_preview", text[:1500])
    return parsed


@router.post("/api/save", dependencies=[RequireEditSettings])
async def save_template(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    broadcaster: Optional[str] = Form(None),
    version: str = Form("1.0"),
    description: Optional[str] = Form(None),
    video_specs: Optional[str] = Form(None),       # JSON string
    audio_specs: Optional[str] = Form(None),
    text_specs: Optional[str] = Form(None),
    head_format: Optional[str] = Form(None),
    textless_format: Optional[str] = Form(None),
    naming_convention: Optional[str] = Form(None),
    archive_specs: Optional[str] = Form(None),
    metadata_requirements: Optional[str] = Form(None),
    ai_generated: bool = Form(False),
    ai_confidence: Optional[float] = Form(None),
    source_document_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Crea un nuovo DeliveryTemplate. Tutti i blocchi JSON sono passati come
    stringhe (FormData), il backend fa parse + valida-via-json.loads."""

    def _parse(s: Optional[str]) -> Optional[dict]:
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON malformato in uno dei blocchi: {e}")

    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code or not name:
        raise HTTPException(400, "code e name sono obbligatori")

    existing = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.tenant_id == CURRENT_TENANT,
        DeliveryTemplate.code == code,
    ).first()
    if existing:
        raise HTTPException(409, f"Esiste già un template con code='{code}'")

    t = DeliveryTemplate(
        tenant_id=CURRENT_TENANT,
        code=code,
        name=name,
        broadcaster=(broadcaster or "").strip() or None,
        version=(version or "1.0").strip(),
        description=(description or "").strip() or None,
        video_specs=_parse(video_specs),
        audio_specs=_parse(audio_specs),
        text_specs=_parse(text_specs),
        head_format=_parse(head_format),
        textless_format=_parse(textless_format),
        naming_convention=_parse(naming_convention),
        archive_specs=_parse(archive_specs),
        metadata_requirements=_parse(metadata_requirements),
        source_document_name=source_document_name,
        ai_generated=ai_generated,
        ai_confidence=ai_confidence,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _dt_dict(t)


@router.put("/api/{template_id}", dependencies=[RequireEditSettings])
async def update_template(
    template_id: int,
    request: Request,
    code: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    broadcaster: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    video_specs: Optional[str] = Form(None),
    audio_specs: Optional[str] = Form(None),
    text_specs: Optional[str] = Form(None),
    head_format: Optional[str] = Form(None),
    textless_format: Optional[str] = Form(None),
    naming_convention: Optional[str] = Form(None),
    archive_specs: Optional[str] = Form(None),
    metadata_requirements: Optional[str] = Form(None),
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == CURRENT_TENANT,
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")

    def _parse(s: Optional[str]) -> Optional[dict]:
        if s is None:
            return None
        try:
            return json.loads(s) if s.strip() else None
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON malformato: {e}")

    if code is not None: t.code = code.strip().upper()
    if name is not None: t.name = name.strip()
    if broadcaster is not None: t.broadcaster = (broadcaster.strip() or None)
    if version is not None: t.version = version.strip() or "1.0"
    if description is not None: t.description = (description.strip() or None)
    if video_specs is not None: t.video_specs = _parse(video_specs)
    if audio_specs is not None: t.audio_specs = _parse(audio_specs)
    if text_specs is not None: t.text_specs = _parse(text_specs)
    if head_format is not None: t.head_format = _parse(head_format)
    if textless_format is not None: t.textless_format = _parse(textless_format)
    if naming_convention is not None: t.naming_convention = _parse(naming_convention)
    if archive_specs is not None: t.archive_specs = _parse(archive_specs)
    if metadata_requirements is not None: t.metadata_requirements = _parse(metadata_requirements)
    if is_active is not None: t.is_active = is_active
    db.commit()
    db.refresh(t)
    return _dt_dict(t)


@router.delete("/api/{template_id}", dependencies=[RequireEditSettings])
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == CURRENT_TENANT,
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")
    # Soft-delete: i template referenziati da JobDeliverable non vanno persi
    t.is_active = False
    db.commit()
    return {"ok": True, "id": template_id, "soft_deleted": True}
