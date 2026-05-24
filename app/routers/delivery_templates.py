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
from app.models import DeliveryTemplate, PriceItem, PriceCategory
from app.services.rbac import requires_permission, current_user_optional
from app.context import current_tenant_id

router = APIRouter(prefix="/delivery-templates", tags=["delivery-templates"])

# nel catalogo (era residuo pre-α.66.15.3). I router mutator usano
# "manage_settings_global" come da rbac.can_edit_settings.
RequireEditSettings = Depends(requires_permission("manage_settings_global"))


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
        .filter(DeliveryTemplate.tenant_id == current_tenant_id())
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
        .filter(DeliveryTemplate.tenant_id == current_tenant_id())
        .order_by(DeliveryTemplate.broadcaster.asc(), DeliveryTemplate.name.asc())
        .all()
    )
    return [_dt_dict(t) for t in rows]


# v3.5.0-alpha.131 (Fase 5) — Diagnostica corpus capitolati: incrocia
# file fisici in docs/capitolati_esempio/ con DeliveryTemplate salvati
# nel DB (match per source_document_name). UI mostra ✓ parsato / ⏳ no.
@router.get("/api/samples-status", dependencies=[RequireEditSettings])
async def samples_corpus_status(db: Session = Depends(get_db)):
    """Report status corpus capitolati. Per ogni file in
    docs/capitolati_esempio/ ritorna: filename, size, ext, parsed (bool),
    template_id (se DeliveryTemplate esistente per quel source_document)."""
    from pathlib import Path as _Path
    proj_root = _Path(__file__).resolve().parents[2]
    samples_dir = proj_root / "docs" / "capitolati_esempio"
    if not samples_dir.is_dir():
        return {"samples": [], "stats": {"total": 0, "parsed": 0}}
    allowed_ext = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}
    # Lookup template per source_document_name (case-insensitive)
    templates = (
        db.query(DeliveryTemplate)
        .filter(DeliveryTemplate.tenant_id == current_tenant_id())
        .filter(DeliveryTemplate.is_active == True)  # noqa: E712
        .all()
    )
    parsed_by_src = {
        (t.source_document_name or "").lower(): t
        for t in templates if t.source_document_name
    }
    out = []
    n_parsed = 0
    for p in sorted(samples_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in allowed_ext:
            continue
        size = p.stat().st_size
        if size == 0:
            continue
        tpl = parsed_by_src.get(p.name.lower())
        if tpl:
            n_parsed += 1
        out.append({
            "filename": p.name,
            "size": size,
            "size_human": f"{size / 1024:.0f} KB" if size < 1024*1024 else f"{size / (1024*1024):.1f} MB",
            "ext": p.suffix.lower().lstrip("."),
            "parsed": tpl is not None,
            "template_id": tpl.id if tpl else None,
            "template_name": tpl.name if tpl else None,
            "template_broadcaster": tpl.broadcaster if tpl else None,
        })
    return {
        "samples": out,
        "stats": {
            "total": len(out),
            "parsed": n_parsed,
            "pending": len(out) - n_parsed,
        },
    }


# v3.5.0-alpha.128 (Fase 5) — IMPORTANTE: deve stare PRIMA di /api/{template_id}
# altrimenti FastAPI lo cattura come template_id="sample-files" → 422.
@router.get("/api/sample-files", dependencies=[RequireEditSettings])
async def list_sample_capitolati():
    """v3.5.0-alpha.128 (Fase 5) — Lista i capitolati di esempio del
    repository (docs/capitolati_esempio/) per quick-load nella UI import
    senza upload manuale. Solo file non vuoti, estensioni supportate
    dal parser AI."""
    from pathlib import Path as _Path
    proj_root = _Path(__file__).resolve().parents[2]
    samples_dir = proj_root / "docs" / "capitolati_esempio"
    if not samples_dir.is_dir():
        return {"samples": []}
    allowed_ext = {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".txt", ".md"}
    out = []
    for p in sorted(samples_dir.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() not in allowed_ext:
            continue
        size = p.stat().st_size
        if size == 0:
            continue
        out.append({
            "filename": p.name,
            "size": size,
            "size_human": f"{size / 1024:.0f} KB" if size < 1024*1024 else f"{size / (1024*1024):.1f} MB",
            "ext": p.suffix.lower().lstrip("."),
        })
    return {"samples": out}


@router.post("/api/parse-batch-pending", dependencies=[RequireEditSettings])
async def parse_batch_pending(request: Request, db: Session = Depends(get_db),
                              auto_save: bool = False):
    """v3.5.0-alpha.154 — Parse batch di tutti i capitolati pending nel corpus.
    Pending = file in docs/capitolati_esempio/ senza DeliveryTemplate creato
    (no match su source_document_name). Idempotente: skippa già parsati.

    Param `auto_save=True` salva i DeliveryTemplate generati. Default False
    (dry-run: ritorna risultati senza persisterli)."""
    from pathlib import Path as _Path
    proj_root = _Path(__file__).resolve().parents[2]
    samples_dir = (proj_root / "docs" / "capitolati_esempio").resolve()
    if not samples_dir.is_dir():
        return {"processed": [], "skipped": [], "errors": []}
    from app.services.deliverables_parser import (
        extract_text_from_file, parse_delivery_template,
    )
    # Lista file + esclude quelli già parsati
    existing_names = {
        t.source_document_name for t in db.query(DeliveryTemplate.source_document_name).filter(
            DeliveryTemplate.source_document_name.isnot(None)
        ).all() if t.source_document_name
    }
    processed = []
    skipped = []
    errors = []
    user = current_user_optional(request)
    for fpath in sorted(samples_dir.iterdir()):
        if not fpath.is_file():
            continue
        if fpath.name in existing_names:
            skipped.append({"file": fpath.name, "reason": "già parsato"})
            continue
        try:
            content = fpath.read_bytes()
            if len(content) == 0:
                errors.append({"file": fpath.name, "error": "file vuoto"})
                continue
            text = extract_text_from_file(content, fpath.name)
            if not text or len(text.strip()) < 20:
                errors.append({"file": fpath.name, "error": "testo estratto troppo breve"})
                continue
            result = parse_delivery_template(text)
            if not result:
                errors.append({"file": fpath.name, "error": "parser AI ritornato vuoto"})
                continue
            result["source_document_name"] = fpath.name
            if auto_save:
                # Inline save (no helper esterno). Replica pattern create_template.
                code = (result.get("code") or "").strip().upper() or f"AI-{fpath.stem[:30]}".upper()
                name = (result.get("name") or "").strip() or fpath.stem
                # Skip se code esiste già (idempotente)
                existing_code = db.query(DeliveryTemplate).filter(
                    DeliveryTemplate.tenant_id == current_tenant_id(),
                    DeliveryTemplate.code == code,
                ).first()
                if existing_code:
                    skipped.append({"file": fpath.name, "reason": f"code '{code}' già esistente"})
                    continue
                try:
                    tpl = DeliveryTemplate(
                        tenant_id=current_tenant_id(),
                        code=code, name=name,
                        broadcaster=result.get("broadcaster"),
                        description=result.get("description"),
                        version=result.get("version", "1.0"),
                        video_specs=result.get("video_specs"),
                        audio_specs=result.get("audio_specs"),
                        text_specs=result.get("text_specs"),
                        head_format=result.get("head_format"),
                        textless_format=result.get("textless_format"),
                        naming_convention=result.get("naming_convention"),
                        archive_specs=result.get("archive_specs"),
                        metadata_requirements=result.get("metadata_requirements"),
                        suggested_items=result.get("suggested_items"),
                        source_document_name=fpath.name,
                        ai_generated=True,
                        ai_confidence=result.get("ai_confidence"),
                    )
                    db.add(tpl)
                    db.commit()
                    db.refresh(tpl)
                    processed.append({"file": fpath.name, "template_id": tpl.id,
                                      "code": code, "name": name,
                                      "confidence": result.get("ai_confidence")})
                except Exception as e:
                    db.rollback()
                    errors.append({"file": fpath.name, "error": f"save failed: {str(e)[:160]}"})
            else:
                processed.append({"file": fpath.name,
                                  "confidence": result.get("ai_confidence"),
                                  "code": result.get("code"),
                                  "name": result.get("name"),
                                  "dry_run": True})
        except Exception as e:
            errors.append({"file": fpath.name, "error": str(e)[:200]})
    return {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "auto_save": auto_save,
        "summary": f"{len(processed)} processati, {len(skipped)} skip, {len(errors)} errori",
    }


@router.post("/api/parse-sample", dependencies=[RequireEditSettings])
async def parse_sample_capitolato(
    request: Request,
    filename: str = Form(...),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.128 (Fase 5) — Parse capitolato dalla directory di
    esempio docs/capitolati_esempio/ senza upload. Sicurezza: filename
    valida via whitelist directory + no path traversal.

    v3.5.0-alpha.172.71 — Usa AI provider PER-UTENTE (era fallback global che
    falliva se .env AI_PROVIDER=disabled). Errori AI restituiti come 503
    user-friendly invece di 500 generico.
    """
    from pathlib import Path as _Path
    proj_root = _Path(__file__).resolve().parents[2]
    samples_dir = (proj_root / "docs" / "capitolati_esempio").resolve()
    # Sanitize: no path separators o ".." nel filename
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "filename non valido")
    fpath = (samples_dir / filename).resolve()
    # Verifica path è dentro samples_dir (no traversal)
    try:
        fpath.relative_to(samples_dir)
    except ValueError:
        raise HTTPException(400, "filename fuori scope")
    if not fpath.is_file():
        raise HTTPException(404, f"Esempio non trovato: {filename}")
    if fpath.stat().st_size == 0:
        raise HTTPException(400, "File esempio vuoto")
    # Verifica provider AI configurato per utente (o fallback global)
    from app.services.ai_provider import get_provider_for_user, get_provider
    from app.services.rbac import current_user_optional
    user = current_user_optional(request)
    provider = get_provider_for_user(user.id if user else None, db) if user else None
    if not provider:
        provider = get_provider()
    if not provider:
        raise HTTPException(
            503,
            detail={
                "message": (
                    "AI provider non configurato.\n\n"
                    "Per usare il parsing automatico dei capitolati, configura una "
                    "API key in /settings → AI (Claude/OpenAI/Gemini/Ollama)."
                ),
                "remediation": "configure_ai_provider",
            },
        )
    # Riusa parser via bytes diretti
    content = fpath.read_bytes()
    from app.services.deliverables_parser import (
        extract_text_from_file, parse_delivery_template,
    )
    text = extract_text_from_file(content, filename)
    if not text or len(text.strip()) < 20:
        raise HTTPException(400, "Estrazione testo fallita o testo troppo breve (<20 caratteri)")
    try:
        result = parse_delivery_template(text)
    except Exception as e:
        raise HTTPException(503, f"Errore AI provider: {e}")
    if not result:
        raise HTTPException(503, "Il parser AI non ha restituito risposta (provider rate-limit o testo non interpretabile)")
    result["source_document_name"] = filename
    result["text_preview"] = text[:200]
    return result


# v3.5.0-alpha.128 — get_template spostato DOPO sample-files/parse-sample
# per evitare path conflict con /api/{template_id} che catturava "sample-files".
@router.get("/api/{template_id}")
async def get_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")
    return _dt_dict(t)


# v3.5.0-alpha.132 — QoL: export JSON + duplica template
@router.get("/api/{template_id}/export-json")
async def export_template_json(template_id: int, db: Session = Depends(get_db)):
    """Scarica template DeliveryTemplate come JSON file (8 blocchi +
    metadata). Utile per backup, share con altre installazioni, audit."""
    import json as _json
    from fastapi.responses import Response
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")
    data = _dt_dict(t)
    safe_code = (t.code or f"template-{t.id}").replace("/", "-").replace(" ", "_")
    payload = _json.dumps(data, indent=2, ensure_ascii=False, default=str)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_code}.json"'},
    )


@router.post("/api/{template_id}/duplicate", dependencies=[RequireEditSettings])
async def duplicate_template(template_id: int, db: Session = Depends(get_db)):
    """Duplica un DeliveryTemplate esistente. Il duplicato:
    - eredita tutti gli 8 blocchi (deepcopy)
    - code += '-copy', name += ' (copia)'
    - ai_generated=False (è una manipolazione manuale)
    - source_document_name=None (non eredita link a file sorgente)
    - is_active=True
    """
    import copy
    src = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not src:
        raise HTTPException(404, "Template sorgente non trovato")
    new = DeliveryTemplate(
        tenant_id=current_tenant_id(),
        code=(src.code or "TEMPLATE") + "-copy",
        name=(src.name or "Senza nome") + " (copia)",
        broadcaster=src.broadcaster,
        description=src.description,
        version=src.version,
        video_specs=copy.deepcopy(src.video_specs) if src.video_specs else None,
        audio_specs=copy.deepcopy(src.audio_specs) if src.audio_specs else None,
        text_specs=copy.deepcopy(src.text_specs) if src.text_specs else None,
        head_format=copy.deepcopy(src.head_format) if src.head_format else None,
        textless_format=copy.deepcopy(src.textless_format) if src.textless_format else None,
        naming_convention=copy.deepcopy(src.naming_convention) if src.naming_convention else None,
        archive_specs=copy.deepcopy(src.archive_specs) if src.archive_specs else None,
        metadata_requirements=copy.deepcopy(src.metadata_requirements) if src.metadata_requirements else None,
        suggested_items=copy.deepcopy(src.suggested_items) if src.suggested_items else None,
        ai_generated=False,
        ai_confidence=None,
        source_document_name=None,
        is_active=True,
    )
    db.add(new)
    db.commit()
    db.refresh(new)
    return _dt_dict(new)


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
    suggested_items: Optional[str] = Form(None),  # v3.5.0-alpha.68.6
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

    def _parse_list(s: Optional[str]) -> Optional[list]:
        if not s:
            return None
        try:
            v = json.loads(s)
            if not isinstance(v, list):
                raise HTTPException(400, "suggested_items deve essere lista")
            return v
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON malformato suggested_items: {e}")

    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code or not name:
        raise HTTPException(400, "code e name sono obbligatori")

    existing = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.tenant_id == current_tenant_id(),
        DeliveryTemplate.code == code,
    ).first()
    if existing:
        raise HTTPException(409, f"Esiste già un template con code='{code}'")

    t = DeliveryTemplate(
        tenant_id=current_tenant_id(),
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
        suggested_items=_parse_list(suggested_items),
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
    suggested_items: Optional[str] = Form(None),  # v3.5.0-alpha.68.6
    is_active: Optional[bool] = Form(None),
    db: Session = Depends(get_db),
):
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")

    def _parse_dict(s: Optional[str]) -> Optional[dict]:
        if s is None:
            return None
        try:
            return json.loads(s) if s.strip() else None
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON malformato: {e}")

    def _parse_list(s: Optional[str]) -> Optional[list]:
        if s is None:
            return None
        try:
            v = json.loads(s) if s.strip() else None
            if v is not None and not isinstance(v, list):
                raise HTTPException(400, "suggested_items deve essere una lista")
            return v
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"JSON malformato suggested_items: {e}")

    if code is not None: t.code = code.strip().upper()
    if name is not None: t.name = name.strip()
    if broadcaster is not None: t.broadcaster = (broadcaster.strip() or None)
    if version is not None: t.version = version.strip() or "1.0"
    if description is not None: t.description = (description.strip() or None)
    if video_specs is not None: t.video_specs = _parse_dict(video_specs)
    if audio_specs is not None: t.audio_specs = _parse_dict(audio_specs)
    if text_specs is not None: t.text_specs = _parse_dict(text_specs)
    if head_format is not None: t.head_format = _parse_dict(head_format)
    if textless_format is not None: t.textless_format = _parse_dict(textless_format)
    if naming_convention is not None: t.naming_convention = _parse_dict(naming_convention)
    if archive_specs is not None: t.archive_specs = _parse_dict(archive_specs)
    if metadata_requirements is not None: t.metadata_requirements = _parse_dict(metadata_requirements)
    if suggested_items is not None: t.suggested_items = _parse_list(suggested_items)
    if is_active is not None: t.is_active = is_active
    db.commit()
    db.refresh(t)
    return _dt_dict(t)


@router.get("/api/{template_id}/suggested-hydrated")
async def hydrated_suggested_items(template_id: int, db: Session = Depends(get_db)):
    """v3.5.0-alpha.68.6 — Ritorna `suggested_items` espandendo i price_item
    referenziati (name, unit, price_list, category). Usato dalla UI editor
    e dal selector "Carica da template" in /quotes."""
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")
    items = t.suggested_items or []
    pi_ids = [int(it["price_item_id"]) for it in items if it.get("price_item_id")]
    pi_map: dict[int, PriceItem] = {}
    if pi_ids:
        rows = db.query(PriceItem).options().filter(
            PriceItem.id.in_(pi_ids),
            PriceItem.tenant_id == current_tenant_id(),
        ).all()
        pi_map = {p.id: p for p in rows}
    out = []
    for it in items:
        pid = it.get("price_item_id")
        p = pi_map.get(int(pid)) if pid else None
        out.append({
            "price_item_id": pid,
            "qty_hint": it.get("qty_hint") or 1,
            "section": it.get("section"),  # A/B/C raggruppamento quote
            "notes": it.get("notes"),
            # Hydrated fields (None se price_item cancellato)
            "name": p.name if p else None,
            "unit": p.unit if p else None,
            "price_list": p.price_list if p else None,
            "category": (p.category.name if (p and p.category) else None),
            "department_id": p.department_id if p else None,
            "missing": p is None,
        })
    return {
        "template_id": t.id,
        "template_code": t.code,
        "template_name": t.name,
        "items": out,
        "items_count": len(out),
        "missing_count": sum(1 for r in out if r["missing"]),
    }


# ── Fase 5 (α.95): import capitolato → match listino → quote bozza ───
# v3.5.0-alpha.95: cabla deliverables_parser + match_deliverables_to_pricelist
# in un wizard 3-step:
#   1. Upload + parse → 8 blocchi DeliveryTemplate + lista deliverables
#   2. Match AI con listino attivo (confidence high/medium/low)
#   3. Generazione Quote bozza con N QuoteLine linkate ai price_item


@router.post("/api/parse-and-match", dependencies=[RequireEditSettings])
async def parse_and_match(
    file: UploadFile = File(...),
    hint: Optional[str] = Form(None),
    include_template: int = Form(1),   # 1 = parsa anche i 8 blocchi DeliveryTemplate
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.95 — Estrae testo + parser AI deliverables + match listino
    in una sola call. Ritorna preview JSON, NON salva nulla. La UI usa il
    payload per la tabella "voci capitolato ↔ voce listino" con override.
    """
    from app.services.deliverables_parser import (
        extract_text_from_file, parse_deliverables,
        parse_delivery_template, match_deliverables_to_pricelist,
    )
    if not file.filename:
        raise HTTPException(400, "Nome file mancante")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "File vuoto")
    text = extract_text_from_file(file_bytes, file.filename)
    if not text or len(text.strip()) < 20:
        raise HTTPException(400, "Estrazione testo fallita (<20 caratteri).")

    # Step 1: deliverables (lista voci operative)
    parsed = parse_deliverables(text, hint=hint)
    if parsed is None:
        raise HTTPException(503, "AI provider non disponibile. Configura in /settings.")
    deliverables = parsed.get("deliverables") or []

    # Step 2: matching listino
    pricelist = db.query(PriceItem).options(
        # PriceItem.category è relationship → eager load
    ).filter(
        PriceItem.tenant_id == current_tenant_id(),
        PriceItem.is_active == True,  # noqa: E712
    ).all()
    pi_payload = [{
        "id": p.id, "name": p.name, "category": (p.category.name if p.category else None),
        "unit": p.unit, "price_list": p.price_list,
    } for p in pricelist]
    match_result = (match_deliverables_to_pricelist(deliverables, pi_payload)
                    if deliverables else None) or {"matches": []}
    matches_by_idx = {m["deliverable_index"]: m for m in match_result.get("matches", [])
                      if isinstance(m, dict) and "deliverable_index" in m}

    # Allinea deliverables con match
    pi_map = {p.id: p for p in pricelist}
    enriched_deliverables = []
    for i, d in enumerate(deliverables):
        m = matches_by_idx.get(i, {})
        pid = m.get("price_item_id")
        pi = pi_map.get(pid) if pid else None
        enriched_deliverables.append({
            "index": i,
            **d,
            "match_price_item_id": pid,
            "match_confidence": m.get("confidence"),
            "match_reasoning": m.get("reasoning"),
            "match_name": pi.name if pi else None,
            "match_unit": pi.unit if pi else None,
            "match_price_list": pi.price_list if pi else None,
            "match_category": (pi.category.name if (pi and pi.category) else None),
        })

    # Step 3 (opz.): 8 blocchi DeliveryTemplate
    template_blocks = None
    if include_template:
        try:
            template_blocks = parse_delivery_template(text)
        except Exception as e:
            import logging; logging.getLogger(__name__).warning(f"parse_delivery_template error: {e}")
            template_blocks = None

    return {
        "filename": file.filename,
        "text_preview": text[:1500],
        "project_info": parsed.get("project_info") or {},
        "global_notes": parsed.get("global_notes"),
        "deliverables": enriched_deliverables,
        "deliverables_count": len(enriched_deliverables),
        "match_stats": {
            "matched": sum(1 for d in enriched_deliverables if d["match_price_item_id"]),
            "unmatched": sum(1 for d in enriched_deliverables if not d["match_price_item_id"]),
            "high_confidence": sum(1 for d in enriched_deliverables if d["match_confidence"] == "high"),
        },
        "template_blocks": template_blocks,
        "pricelist_size": len(pi_payload),
    }


@router.post("/api/create-quote-from-deliverables", dependencies=[RequireEditSettings])
async def create_quote_from_deliverables(
    request: Request,
    project_id: int = Form(...),
    title: str = Form(...),
    deliverables_json: str = Form(...),   # JSON array {description, detail, quantity, unit, section, price_item_id?, unit_price?}
    valid_until: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.95 — Genera una Quote BOZZA con N QuoteLine partendo
    dai deliverables AI-matchati. L'utente ha già confermato i match nella
    UI; qui crea l'oggetto in stato draft. La quote non è inviata.

    Numero quote auto (Q-{anno}-NNN, riusa pattern di /quotes).
    """
    from app.models import Quote, QuoteLine, QuoteStatus, Project, PriceLevel
    from datetime import date as _date

    p = db.query(Project).filter(
        Project.id == project_id, Project.tenant_id == current_tenant_id(),
    ).first()
    if not p:
        raise HTTPException(404, f"Project {project_id} non trovato")
    try:
        deliverables = json.loads(deliverables_json)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"deliverables_json malformato: {e}")
    if not isinstance(deliverables, list) or not deliverables:
        raise HTTPException(400, "deliverables_json deve essere lista non vuota")

    # Auto-numero Q-YYYY-NNN (riusa pattern numbering)
    from app.services.numbering import next_year_progressive
    quote_number = next_year_progressive(
        db, Quote, base="Q", code_field="number",
        include_deleted=True,
        extra_filter=(Quote.tenant_id == current_tenant_id()),
    )

    issue = _date.today()
    valid = None
    if valid_until:
        try:
            valid = _date.fromisoformat(valid_until)
        except ValueError:
            pass
    q = Quote(
        tenant_id=current_tenant_id(),
        number=quote_number,
        version=1,
        project_id=p.id,
        client_id=p.client_id,
        title=title.strip()[:255],
        status=QuoteStatus.draft,
        issue_date=issue,
        valid_until=valid,
        notes=(notes or "").strip() or None,
    )
    db.add(q); db.flush()

    lines_created = 0
    section_counters = {}  # per section, increment position
    for d in deliverables:
        if not isinstance(d, dict):
            continue
        desc = (d.get("description") or "").strip()
        if not desc:
            continue
        section = (d.get("section") or "A").upper()[:5]
        section_counters[section] = section_counters.get(section, 0) + 1
        position = f"{section}.{section_counters[section]}"
        unit_price = d.get("unit_price")
        pid = d.get("price_item_id")
        # Se non override esplicito e c'è price_item, eredita prezzo listino
        if (unit_price is None or unit_price == "") and pid:
            pi = db.query(PriceItem).filter(PriceItem.id == int(pid)).first()
            if pi and pi.price_list is not None:
                unit_price = pi.price_list
        try:
            unit_price = float(unit_price) if unit_price is not None else 0.0
        except (TypeError, ValueError):
            unit_price = 0.0
        qty = float(d.get("quantity") or 1.0)
        total = round(qty * unit_price, 2)
        line = QuoteLine(
            quote_id=q.id,
            price_item_id=int(pid) if pid else None,
            section=section,
            position=position,
            description=desc[:255],
            detail=(d.get("detail") or None),
            quantity=qty,
            unit=(d.get("unit") or "pc")[:20],
            price_level=PriceLevel.list_price,
            unit_price=unit_price,
            total=total,
            category_override=(d.get("category") or None),
            source_hint="capitolato_ai_import",
            section_label=(d.get("section_label") or None),
        )
        db.add(line)
        lines_created += 1
    db.commit()
    db.refresh(q)
    return {
        "quote_id": q.id,
        "quote_number": q.number,
        "project_id": q.project_id,
        "lines_created": lines_created,
        "status": q.status.value if hasattr(q.status, "value") else str(q.status),
    }


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request, db: Session = Depends(get_db)):
    """v3.5.0-alpha.95 — Wizard `/delivery-templates/import` per import
    capitolato AI + matching listino + generazione Quote bozza."""
    from app.models import Project
    projects = db.query(Project).filter(
        Project.tenant_id == current_tenant_id(),
    ).order_by(Project.created_at.desc()).all()
    return _tpl().TemplateResponse(
        "pages/capitolati_import.html",
        {"request": request, "projects": projects},
    )


@router.delete("/api/{template_id}", dependencies=[RequireEditSettings])
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == template_id,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not t:
        raise HTTPException(404, "Template non trovato")
    # Soft-delete: i template referenziati da JobDeliverable non vanno persi
    t.is_active = False
    db.commit()
    return {"ok": True, "id": template_id, "soft_deleted": True}
