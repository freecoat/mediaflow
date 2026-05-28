"""v3.5.0-alpha.172.114 — Router DeliveryItem + AudioTrackSpec + taxonomy lookup.

Endpoint:
- GET    /delivery-templates/{tid}/items          — lista DeliveryItem del template
- POST   /delivery-templates/{tid}/items          — crea item manuale
- POST   /delivery-templates/{tid}/items/ai-extract — parse capitolato (re-parsing) → materialize items
- GET    /delivery-items/{iid}                    — dettaglio item + tracce audio
- PUT    /delivery-items/{iid}                    — update item (Form per campo)
- DELETE /delivery-items/{iid}                    — soft-delete
- POST   /delivery-items/{iid}/audio-tracks       — aggiungi traccia audio
- PUT    /delivery-audio-tracks/{aid}             — update audio track
- DELETE /delivery-audio-tracks/{aid}             — delete audio track
- GET    /delivery-taxonomy                       — vocabolario completo per dropdown UI
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models.models import (
    DeliveryTemplate, DeliveryItem, AudioTrackSpec,
    Package, Container, VideoCodec, AudioCodec, AudioChannelConfig,
    AudioMixType, MixStandard, Resolution, FrameRate,
)
from app.services.rbac import requires_permission, current_user_optional
from app.context import current_tenant_id
from app.services.delivery_timeline_service import effective_timeline

logger = logging.getLogger(__name__)
router = APIRouter(tags=["delivery_items"])
templates_engine = Jinja2Templates(directory="app/templates")

RequireEdit = Depends(requires_permission("manage_settings_global"))


@router.get("/settings/delivery-taxonomy", response_class=HTMLResponse)
async def delivery_taxonomy_page(request: Request):
    """Pagina UI admin per gestire taxonomy delivery."""
    return templates_engine.TemplateResponse(
        "pages/delivery_taxonomy.html", {"request": request},
    )


# ── Serializers ─────────────────────────────────────────────

def _serialize_track(t: AudioTrackSpec) -> dict:
    return {
        "id": t.id,
        "delivery_item_id": t.delivery_item_id,
        "sort_order": t.sort_order,
        "track_label": t.track_label,
        "channel_config_id": t.channel_config_id,
        "mix_type_id": t.mix_type_id,
        "mix_standard_id": t.mix_standard_id,
        "audio_codec_id": t.audio_codec_id,
        "sample_rate_hz": t.sample_rate_hz,
        "bit_depth": t.bit_depth,
        "is_optional": t.is_optional,
        "notes": t.notes,
    }


def _serialize_item(it: DeliveryItem, with_tracks: bool = True) -> dict:
    out = {
        "id": it.id,
        "tenant_id": it.tenant_id,
        "delivery_template_id": it.delivery_template_id,
        "name": it.name,
        "sort_order": it.sort_order,
        "package_id": it.package_id,
        "package_variant_notes": it.package_variant_notes,
        "container_id": it.container_id,
        "video_codec_id": it.video_codec_id,
        "video_bit_depth": it.video_bit_depth,
        "chroma_subsampling": it.chroma_subsampling,
        "resolution_id": it.resolution_id,
        "aspect_ratio": it.aspect_ratio,
        "frame_rate_id": it.frame_rate_id,
        "scan_type": it.scan_type,
        "color_space": it.color_space,
        "hdr_format": it.hdr_format,
        "subtitle_format": it.subtitle_format,
        "subtitle_languages": it.subtitle_languages,
        "suggested_unit": it.suggested_unit,
        "suggested_qty": it.suggested_qty,
        "suggested_price_item_id": it.suggested_price_item_id,
        "extra_specs": it.extra_specs,
        "notes": it.notes,
        "ai_extracted": it.ai_extracted,
        "ai_confidence": it.ai_confidence,
        "pending_review": it.pending_review,
        "is_active": it.is_active,
        # timeline + audio-config (v3.5.0-alpha.172.127)
        "tc_start": it.tc_start,
        "program_start": it.program_start,
        "timeline_segments": it.timeline_segments or [],
        "audio_config_preset_id": it.audio_config_preset_id,
        "audio_config_code": it.audio_config_code,
    }
    if with_tracks:
        out["audio_tracks"] = [_serialize_track(t) for t in sorted(it.audio_tracks, key=lambda x: x.sort_order)]
    return out


def _scoped_taxonomy(db: Session, tenant_id: int):
    """Helper: return per-tenant + global preset records, active only, ordered."""
    def _q(Model):
        return db.query(Model).filter(
            or_(Model.tenant_id == tenant_id, Model.tenant_id.is_(None)),
            Model.is_active == True,  # noqa: E712
        ).order_by(Model.sort_order, Model.id).all()
    return _q


# ── Items: list / detail / CRUD ─────────────────────────────

@router.get("/delivery-templates/api/{tid}/items")
async def list_items(tid: int, db: Session = Depends(get_db)):
    """Lista DeliveryItem di un template (solo attivi)."""
    items = (
        db.query(DeliveryItem)
        .options(selectinload(DeliveryItem.audio_tracks))
        .filter(
            DeliveryItem.delivery_template_id == tid,
            DeliveryItem.tenant_id == current_tenant_id(),
            DeliveryItem.is_active == True,  # noqa: E712
        )
        .order_by(DeliveryItem.sort_order, DeliveryItem.id)
        .all()
    )
    return {"items": [_serialize_item(it) for it in items]}


@router.get("/delivery-items/api/{iid}")
async def get_item(iid: int, db: Session = Depends(get_db)):
    it = (
        db.query(DeliveryItem)
        .options(selectinload(DeliveryItem.audio_tracks))
        .filter(
            DeliveryItem.id == iid,
            DeliveryItem.tenant_id == current_tenant_id(),
        )
        .first()
    )
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")
    data = _serialize_item(it)
    data["effective_timeline"] = effective_timeline(db, it)
    return data


@router.post("/delivery-templates/api/{tid}/items", dependencies=[RequireEdit])
async def create_item_manual(
    tid: int,
    name: str = Form(...),
    package_id: Optional[int] = Form(None),
    container_id: Optional[int] = Form(None),
    video_codec_id: Optional[int] = Form(None),
    video_bit_depth: Optional[int] = Form(None),
    chroma_subsampling: Optional[str] = Form(None),
    resolution_id: Optional[int] = Form(None),
    aspect_ratio: Optional[str] = Form(None),
    frame_rate_id: Optional[int] = Form(None),
    scan_type: Optional[str] = Form(None),
    color_space: Optional[str] = Form(None),
    hdr_format: Optional[str] = Form(None),
    subtitle_format: Optional[str] = Form(None),
    suggested_unit: Optional[str] = Form(None),
    suggested_qty: Optional[float] = Form(None),
    suggested_price_item_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    tpl = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == tid,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not tpl:
        raise HTTPException(404, "DeliveryTemplate non trovato")
    last_sort = db.query(DeliveryItem).filter(
        DeliveryItem.delivery_template_id == tid,
    ).count() * 10
    it = DeliveryItem(
        tenant_id=current_tenant_id(),
        delivery_template_id=tid,
        name=name.strip(),
        sort_order=last_sort,
        package_id=package_id,
        container_id=container_id,
        video_codec_id=video_codec_id,
        video_bit_depth=video_bit_depth,
        chroma_subsampling=chroma_subsampling or None,
        resolution_id=resolution_id,
        aspect_ratio=aspect_ratio or None,
        frame_rate_id=frame_rate_id,
        scan_type=scan_type or None,
        color_space=color_space or None,
        hdr_format=hdr_format or None,
        subtitle_format=subtitle_format or None,
        suggested_unit=suggested_unit or None,
        suggested_qty=suggested_qty,
        suggested_price_item_id=suggested_price_item_id,
        notes=notes or None,
        ai_extracted=False,
    )
    db.add(it)
    db.commit()
    db.refresh(it)
    return _serialize_item(it)


@router.put("/delivery-items/api/{iid}", dependencies=[RequireEdit])
async def update_item(
    iid: int,
    name: Optional[str] = Form(None),
    package_id: Optional[int] = Form(None),
    package_variant_notes: Optional[str] = Form(None),
    container_id: Optional[int] = Form(None),
    video_codec_id: Optional[int] = Form(None),
    video_bit_depth: Optional[int] = Form(None),
    chroma_subsampling: Optional[str] = Form(None),
    resolution_id: Optional[int] = Form(None),
    aspect_ratio: Optional[str] = Form(None),
    frame_rate_id: Optional[int] = Form(None),
    scan_type: Optional[str] = Form(None),
    color_space: Optional[str] = Form(None),
    hdr_format: Optional[str] = Form(None),
    subtitle_format: Optional[str] = Form(None),
    subtitle_languages: Optional[str] = Form(None),  # JSON list
    suggested_unit: Optional[str] = Form(None),
    suggested_qty: Optional[float] = Form(None),
    suggested_price_item_id: Optional[int] = Form(None),
    extra_specs: Optional[str] = Form(None),  # JSON
    notes: Optional[str] = Form(None),
    pending_review: Optional[bool] = Form(None),
    sort_order: Optional[int] = Form(None),
    # timeline + audio-config (v3.5.0-alpha.172.127)
    tc_start: Optional[str] = Form(None),
    program_start: Optional[str] = Form(None),
    timeline_segments_json: Optional[str] = Form(None),
    audio_config_preset_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    it = db.query(DeliveryItem).filter(
        DeliveryItem.id == iid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")

    if name is not None:                     it.name = name.strip()
    if package_id is not None:               it.package_id = package_id or None
    if package_variant_notes is not None:    it.package_variant_notes = package_variant_notes.strip() or None
    if container_id is not None:             it.container_id = container_id or None
    if video_codec_id is not None:           it.video_codec_id = video_codec_id or None
    if video_bit_depth is not None:          it.video_bit_depth = video_bit_depth or None
    if chroma_subsampling is not None:       it.chroma_subsampling = chroma_subsampling.strip() or None
    if resolution_id is not None:            it.resolution_id = resolution_id or None
    if aspect_ratio is not None:             it.aspect_ratio = aspect_ratio.strip() or None
    if frame_rate_id is not None:            it.frame_rate_id = frame_rate_id or None
    if scan_type is not None:                it.scan_type = scan_type.strip() or None
    if color_space is not None:              it.color_space = color_space.strip() or None
    if hdr_format is not None:               it.hdr_format = hdr_format.strip() or None
    if subtitle_format is not None:          it.subtitle_format = subtitle_format.strip() or None
    if subtitle_languages is not None:
        try:
            v = json.loads(subtitle_languages) if subtitle_languages.strip() else None
            if v is not None and not isinstance(v, list):
                raise ValueError("must be list")
            it.subtitle_languages = v
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(400, f"subtitle_languages JSON invalido: {e}")
    if suggested_unit is not None:           it.suggested_unit = suggested_unit.strip() or None
    if suggested_qty is not None:            it.suggested_qty = suggested_qty
    if suggested_price_item_id is not None:  it.suggested_price_item_id = suggested_price_item_id or None
    if extra_specs is not None:
        try:
            it.extra_specs = json.loads(extra_specs) if extra_specs.strip() else None
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"extra_specs JSON invalido: {e}")
    if notes is not None:                    it.notes = notes.strip() or None
    if pending_review is not None:           it.pending_review = pending_review
    if sort_order is not None:               it.sort_order = sort_order

    # timeline + audio-config (v3.5.0-alpha.172.127)
    if tc_start is not None:
        it.tc_start = tc_start.strip() or None
    if program_start is not None:
        it.program_start = program_start.strip() or None
    if timeline_segments_json is not None:
        try:
            v = json.loads(timeline_segments_json) if timeline_segments_json.strip() else []
            if not isinstance(v, list):
                raise ValueError("must be list")
            it.timeline_segments = v
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(400, f"timeline_segments_json invalido: {e}")
    if audio_config_preset_id is not None:
        pid = int(audio_config_preset_id) if str(audio_config_preset_id).strip() else None
        if pid:
            from app.models.models import AudioConfigPreset
            from app.services.audio_config_service import apply_audio_config_preset
            # Tenant-scoped lookup (no cross-tenant leak via PK): filtra tenant_id
            # + verifica ownership template prima di applicare.
            preset = (db.query(AudioConfigPreset)
                      .filter(AudioConfigPreset.id == pid,
                              AudioConfigPreset.tenant_id == current_tenant_id())
                      .first())
            if preset and preset.delivery_template_id == it.delivery_template_id:
                apply_audio_config_preset(db, it, preset)
        else:
            it.audio_config_preset_id = None
            it.audio_config_code = None

    db.commit()
    db.refresh(it)
    return _serialize_item(it)


@router.delete("/delivery-items/api/{iid}", dependencies=[RequireEdit])
async def delete_item(iid: int, db: Session = Depends(get_db)):
    """Soft-delete (is_active=False)."""
    it = db.query(DeliveryItem).filter(
        DeliveryItem.id == iid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")
    it.is_active = False
    db.commit()
    return {"ok": True, "id": iid}


# ── Validazione cross-tier α.172.121 (Tier 3 Bundle B) ────────

@router.get("/delivery-items/api/{iid}/validate")
async def validate_item_endpoint(iid: int, db: Session = Depends(get_db)):
    """Verifica compatibilità FK dell'item. Non muta nulla."""
    from app.services.delivery_item_validation import validate_summary
    it = db.query(DeliveryItem).filter(
        DeliveryItem.id == iid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")
    return validate_summary(db, it)


@router.post("/delivery-items/api/{iid}/revalidate-ai", dependencies=[RequireEdit])
async def revalidate_item_ai(iid: int, request: Request, db: Session = Depends(get_db)):
    """Re-esegue pass2 mapping FK via AI sul singolo item, usando la
    taxonomy correntemente attiva. Utile dopo aggiunta nuovi preset.

    L'item conserva il `name` e tutti i campi text liberi
    (extra_specs/notes); vengono ricalcolati solo i FK
    (package/container/codec/resolution/framerate/audio).
    """
    from app.services.ai_provider import get_provider_for_user, get_provider
    from app.services.delivery_items_parser import (
        _taxonomy_dict_for_pass2, PASS2_SYSTEM_PROMPT, materialize_items,
    )
    import json

    it = db.query(DeliveryItem).filter(
        DeliveryItem.id == iid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")

    user = current_user_optional(request, db)
    user_id = user.id if user else 1
    provider = get_provider_for_user(user_id, db) or get_provider()
    if not provider:
        raise HTTPException(503, "Nessun provider AI configurato.")

    taxonomy = _taxonomy_dict_for_pass2(db, current_tenant_id())
    item_payload = {
        "name": it.name,
        "package": _name_or_none(db, "Package", it.package_id),
        "container": _name_or_none(db, "Container", it.container_id),
        "video_codec": _name_or_none(db, "VideoCodec", it.video_codec_id),
        "video_bit_depth": it.video_bit_depth,
        "chroma_subsampling": it.chroma_subsampling,
        "resolution": _name_or_none(db, "Resolution", it.resolution_id),
        "aspect_ratio": it.aspect_ratio,
        "frame_rate": _name_or_none(db, "FrameRate", it.frame_rate_id),
        "scan_type": it.scan_type,
        "color_space": it.color_space,
        "hdr_format": it.hdr_format,
        "extra_specs": it.extra_specs,
        "notes": it.notes,
    }

    pass2_user = f"""Item da rimappare con taxonomy aggiornata:
{json.dumps([item_payload], ensure_ascii=False)}

Vocabolario taxonomy disponibile:
{json.dumps(taxonomy, ensure_ascii=False)}

Mappa l'item agli id taxonomy. Restituisci JSON {{"items":[...]}}.
"""
    parsed = provider.extract_json(PASS2_SYSTEM_PROMPT, pass2_user, max_tokens=8000)
    if not parsed or "items" not in parsed:
        diag = getattr(provider, "last_extract_diag", {}) or {}
        raise HTTPException(502, f"AI rimapping fallito: {diag.get('error','no msg')[:200]}")

    new_items = parsed.get("items") or []
    if not new_items:
        raise HTTPException(502, "AI non ha restituito mapping.")

    mapped = new_items[0]
    # Applica solo i FK ricalcolati; preserva name + extra_specs + notes originali.
    fk_fields = ("package_id", "container_id", "video_codec_id",
                 "resolution_id", "frame_rate_id")
    updates_applied = {}
    for f in fk_fields:
        new_val = mapped.get(f)
        if new_val is not None and new_val != getattr(it, f):
            old_val = getattr(it, f)
            setattr(it, f, new_val)
            updates_applied[f] = {"from": old_val, "to": new_val}
    # Campi free-text potenzialmente migliorati
    for f in ("chroma_subsampling", "aspect_ratio", "scan_type", "color_space", "hdr_format"):
        new_val = mapped.get(f)
        if new_val is not None and new_val != getattr(it, f):
            old_val = getattr(it, f)
            setattr(it, f, new_val)
            updates_applied[f] = {"from": old_val, "to": new_val}
    it.ai_extracted = True
    db.commit()
    db.refresh(it)
    from app.services.delivery_item_validation import validate_summary
    val = validate_summary(db, it)
    return {
        "ok": True,
        "item": _serialize_item(it),
        "updates_applied": updates_applied,
        "validation": val,
    }


# ── Search globale items α.172.123 (Tier 3 Bundle D) ─────────

@router.get("/delivery-items/api/search")
async def search_items(
    q: str = "",
    package: str = "",
    resolution: str = "",
    hdr: str = "",
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Ricerca cross-template DeliveryItem. Filtri opzionali:
    - q: testo libero (case-insensitive) match su name + notes + color_space
    - package: nome package (es. "DCP", "IMF")
    - resolution: nome o family resolution (es. "UHD", "HD")
    - hdr: HDR format (es. "HDR10", "Dolby Vision")

    Output: lista items + template_code + template_name.
    """
    from app.models.models import (
        Package, Container, Resolution, DeliveryTemplate, VideoCodec,
    )
    tid = current_tenant_id()
    Q = (
        db.query(DeliveryItem, DeliveryTemplate.code, DeliveryTemplate.name,
                 Package.name.label("pkg_name"),
                 Resolution.name.label("res_name"),
                 Container.name.label("cont_name"),
                 VideoCodec.name.label("vc_name"))
        .join(DeliveryTemplate, DeliveryItem.delivery_template_id == DeliveryTemplate.id)
        .outerjoin(Package, DeliveryItem.package_id == Package.id)
        .outerjoin(Container, DeliveryItem.container_id == Container.id)
        .outerjoin(Resolution, DeliveryItem.resolution_id == Resolution.id)
        .outerjoin(VideoCodec, DeliveryItem.video_codec_id == VideoCodec.id)
        .filter(DeliveryItem.tenant_id == tid)
        .filter(DeliveryItem.is_active == True)  # noqa: E712
    )
    if q.strip():
        like = f"%{q.strip().lower()}%"
        from sqlalchemy import func, or_
        Q = Q.filter(or_(
            func.lower(DeliveryItem.name).like(like),
            func.lower(DeliveryItem.notes).like(like),
            func.lower(DeliveryItem.color_space).like(like),
        ))
    if package.strip():
        Q = Q.filter(Package.name.ilike(f"%{package.strip()}%"))
    if resolution.strip():
        from sqlalchemy import or_
        rs = resolution.strip()
        Q = Q.filter(or_(
            Resolution.name.ilike(f"%{rs}%"),
            Resolution.family.ilike(f"%{rs}%"),
        ))
    if hdr.strip():
        Q = Q.filter(DeliveryItem.hdr_format.ilike(f"%{hdr.strip()}%"))

    rows = Q.order_by(DeliveryTemplate.code.asc(), DeliveryItem.sort_order.asc()).limit(max(1, min(limit, 200))).all()
    return {
        "count": len(rows),
        "results": [
            {
                "id": it.id,
                "name": it.name,
                "template_id": it.delivery_template_id,
                "template_code": tcode,
                "template_name": tname,
                "package": pkg,
                "container": cont,
                "video_codec": vc,
                "resolution": res,
                "hdr_format": it.hdr_format,
                "color_space": it.color_space,
                "suggested_unit": it.suggested_unit,
                "suggested_qty": it.suggested_qty,
            }
            for it, tcode, tname, pkg, res, cont, vc in rows
        ],
    }


# ── Diff template α.172.123 (Tier 3 Bundle D) ────────────────

@router.get("/delivery-templates/api/diff")
async def diff_templates(a: int, b: int, db: Session = Depends(get_db)):
    """Confronta 2 template: diff sui 8 blocchi specs + diff lista items.

    Output:
    {
      "a": {id, code, name},
      "b": {id, code, name},
      "blocks": {block_name: {a_keys, b_keys, only_a, only_b, common}},
      "items": {only_in_a: [...], only_in_b: [...], common_names: [...]}
    }
    """
    tid = current_tenant_id()
    ta = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == a, DeliveryTemplate.tenant_id == tid,
    ).first()
    tb = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == b, DeliveryTemplate.tenant_id == tid,
    ).first()
    if not ta or not tb:
        raise HTTPException(404, "Template non trovato")

    block_names = (
        "video_specs", "audio_specs", "text_specs", "head_format",
        "textless_format", "naming_convention", "archive_specs",
        "metadata_requirements",
    )
    blocks = {}
    for bn in block_names:
        av = getattr(ta, bn) or {}
        bv = getattr(tb, bn) or {}
        a_keys = set(av.keys()) if isinstance(av, dict) else set()
        b_keys = set(bv.keys()) if isinstance(bv, dict) else set()
        blocks[bn] = {
            "a_has_data": bool(av),
            "b_has_data": bool(bv),
            "only_a": sorted(a_keys - b_keys),
            "only_b": sorted(b_keys - a_keys),
            "common": sorted(a_keys & b_keys),
        }

    items_a = db.query(DeliveryItem).filter(
        DeliveryItem.delivery_template_id == a,
        DeliveryItem.tenant_id == tid,
        DeliveryItem.is_active == True,  # noqa: E712
    ).all()
    items_b = db.query(DeliveryItem).filter(
        DeliveryItem.delivery_template_id == b,
        DeliveryItem.tenant_id == tid,
        DeliveryItem.is_active == True,  # noqa: E712
    ).all()
    names_a = {(it.name or "").lower(): it.name for it in items_a}
    names_b = {(it.name or "").lower(): it.name for it in items_b}
    set_a = set(names_a.keys())
    set_b = set(names_b.keys())
    return {
        "a": {"id": ta.id, "code": ta.code, "name": ta.name, "items_count": len(items_a)},
        "b": {"id": tb.id, "code": tb.code, "name": tb.name, "items_count": len(items_b)},
        "blocks": blocks,
        "items": {
            "only_in_a": sorted([names_a[k] for k in (set_a - set_b)]),
            "only_in_b": sorted([names_b[k] for k in (set_b - set_a)]),
            "common_names": sorted([names_a[k] for k in (set_a & set_b)]),
        },
    }


# ── AI match listino α.172.122 (Tier 3 Bundle C) ─────────────

@router.post("/delivery-items/api/{iid}/match-pricelist", dependencies=[RequireEdit])
async def match_pricelist_endpoint(iid: int, request: Request, db: Session = Depends(get_db)):
    """AI ranking top 3 PriceItem candidati per linking suggested_price_item_id.

    Output: {"matches": [{"price_item_id": int, "confidence": 0..1, "reason": str,
    "name": str, "category": str, "unit": str}], "diag": str}

    L'endpoint NON applica il match: la UI mostra ranking e l'utente clicca
    per applicare via PUT /delivery-items/api/{iid} con suggested_price_item_id.
    """
    from app.services.ai_provider import get_provider_for_user, get_provider
    from app.services.delivery_item_pricelist_match import match_pricelist_for_item

    it = db.query(DeliveryItem).filter(
        DeliveryItem.id == iid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")

    user = current_user_optional(request, db)
    user_id = user.id if user else 1
    provider = get_provider_for_user(user_id, db) or get_provider()
    # provider può essere None: il service fa fallback heuristic
    return match_pricelist_for_item(db, it, current_tenant_id(), provider)


def _name_or_none(db: Session, model_name: str, fk: Optional[int]) -> Optional[str]:
    """Helper per revalidate-ai: ritorna `name` dato FK + nome modello."""
    if not fk:
        return None
    from app.models.models import (
        Package, Container, VideoCodec, Resolution, FrameRate,
    )
    model_map = {
        "Package": Package, "Container": Container, "VideoCodec": VideoCodec,
        "Resolution": Resolution, "FrameRate": FrameRate,
    }
    M = model_map.get(model_name)
    if not M:
        return None
    rec = db.get(M, fk)
    return rec.name if rec else None


# ── AudioTrackSpec CRUD ─────────────────────────────────────

@router.post("/delivery-items/api/{iid}/audio-tracks", dependencies=[RequireEdit])
async def add_audio_track(
    iid: int,
    track_label: str = Form(...),
    channel_config_id: Optional[int] = Form(None),
    mix_type_id: Optional[int] = Form(None),
    mix_standard_id: Optional[int] = Form(None),
    audio_codec_id: Optional[int] = Form(None),
    sample_rate_hz: Optional[int] = Form(None),
    bit_depth: Optional[int] = Form(None),
    is_optional: bool = Form(False),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    it = db.query(DeliveryItem).filter(
        DeliveryItem.id == iid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not it:
        raise HTTPException(404, "DeliveryItem non trovato")
    last = db.query(AudioTrackSpec).filter(AudioTrackSpec.delivery_item_id == iid).count() * 10
    tr = AudioTrackSpec(
        delivery_item_id=iid,
        sort_order=last,
        track_label=track_label.strip(),
        channel_config_id=channel_config_id or None,
        mix_type_id=mix_type_id or None,
        mix_standard_id=mix_standard_id or None,
        audio_codec_id=audio_codec_id or None,
        sample_rate_hz=sample_rate_hz or None,
        bit_depth=bit_depth or None,
        is_optional=is_optional,
        notes=notes.strip() if notes else None,
    )
    db.add(tr)
    db.commit()
    db.refresh(tr)
    return _serialize_track(tr)


@router.put("/delivery-audio-tracks/api/{aid}", dependencies=[RequireEdit])
async def update_audio_track(
    aid: int,
    track_label: Optional[str] = Form(None),
    channel_config_id: Optional[int] = Form(None),
    mix_type_id: Optional[int] = Form(None),
    mix_standard_id: Optional[int] = Form(None),
    audio_codec_id: Optional[int] = Form(None),
    sample_rate_hz: Optional[int] = Form(None),
    bit_depth: Optional[int] = Form(None),
    is_optional: Optional[bool] = Form(None),
    notes: Optional[str] = Form(None),
    sort_order: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    tr = db.query(AudioTrackSpec).join(DeliveryItem).filter(
        AudioTrackSpec.id == aid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not tr:
        raise HTTPException(404, "AudioTrack non trovato")
    if track_label is not None:       tr.track_label = track_label.strip() or tr.track_label
    if channel_config_id is not None: tr.channel_config_id = channel_config_id or None
    if mix_type_id is not None:       tr.mix_type_id = mix_type_id or None
    if mix_standard_id is not None:   tr.mix_standard_id = mix_standard_id or None
    if audio_codec_id is not None:    tr.audio_codec_id = audio_codec_id or None
    if sample_rate_hz is not None:    tr.sample_rate_hz = sample_rate_hz or None
    if bit_depth is not None:         tr.bit_depth = bit_depth or None
    if is_optional is not None:       tr.is_optional = is_optional
    if notes is not None:             tr.notes = notes.strip() or None
    if sort_order is not None:        tr.sort_order = sort_order
    db.commit()
    db.refresh(tr)
    return _serialize_track(tr)


@router.delete("/delivery-audio-tracks/api/{aid}", dependencies=[RequireEdit])
async def delete_audio_track(aid: int, db: Session = Depends(get_db)):
    tr = db.query(AudioTrackSpec).join(DeliveryItem).filter(
        AudioTrackSpec.id == aid,
        DeliveryItem.tenant_id == current_tenant_id(),
    ).first()
    if not tr:
        raise HTTPException(404, "AudioTrack non trovato")
    db.delete(tr)
    db.commit()
    return {"ok": True, "id": aid}


# ── Taxonomy lookup (dropdowns UI) ──────────────────────────

@router.get("/delivery-taxonomy/api")
async def get_taxonomy(db: Session = Depends(get_db)):
    """Vocabolario completo (preset globali + tenant-owned) per dropdown UI.
    Output ricco: include attributi semantici utili per cliente (typical_use,
    family, channel_count, ecc)."""
    tenant_id = current_tenant_id()
    _q = _scoped_taxonomy(db, tenant_id)
    return {
        "packages": [
            {"id": r.id, "name": r.name, "typical_use": r.typical_use,
             "structure_desc": r.structure_desc, "is_preset_global": r.is_preset_global}
            for r in _q(Package)
        ],
        "containers": [
            {"id": r.id, "name": r.name, "extension": r.extension, "op_pattern": r.op_pattern,
             "is_image_sequence": r.is_image_sequence, "media_kind": r.media_kind,
             "is_preset_global": r.is_preset_global}
            for r in _q(Container)
        ],
        "video_codecs": [
            {"id": r.id, "name": r.name, "family": r.family, "profile_flavor": r.profile_flavor,
             "typical_use": r.typical_use, "is_intermediate": r.is_intermediate,
             "is_preset_global": r.is_preset_global}
            for r in _q(VideoCodec)
        ],
        "audio_codecs": [
            {"id": r.id, "name": r.name, "family": r.family, "is_lossless": r.is_lossless,
             "is_preset_global": r.is_preset_global}
            for r in _q(AudioCodec)
        ],
        "channel_configs": [
            {"id": r.id, "name": r.name, "channel_count": r.channel_count,
             "spec_string": r.spec_string, "is_immersive": r.is_immersive,
             "is_preset_global": r.is_preset_global}
            for r in _q(AudioChannelConfig)
        ],
        "mix_types": [
            {"id": r.id, "name": r.name, "short_label": r.short_label,
             "is_preset_global": r.is_preset_global}
            for r in _q(AudioMixType)
        ],
        "mix_standards": [
            {"id": r.id, "name": r.name, "family": r.family,
             "loudness_target_lufs": r.loudness_target_lufs,
             "true_peak_max_dbtp": r.true_peak_max_dbtp,
             "standard_ref": r.standard_ref, "is_preset_global": r.is_preset_global}
            for r in _q(MixStandard)
        ],
        "resolutions": [
            {"id": r.id, "name": r.name, "width": r.width, "height": r.height,
             "framing_aspect": r.framing_aspect, "family": r.family,
             "is_preset_global": r.is_preset_global}
            for r in _q(Resolution)
        ],
        "frame_rates": [
            {"id": r.id, "name": r.name, "fps": r.fps, "is_drop_frame": r.is_drop_frame,
             "is_ntsc_family": r.is_ntsc_family, "is_preset_global": r.is_preset_global}
            for r in _q(FrameRate)
        ],
    }


# ── Taxonomy admin CRUD (Tier 2.3) ──────────────────────────
#
# Endpoint generici per CRUD su ogni entity taxonomy. Permette ad admin di
# aggiungere/editare/disattivare voci custom tenant-specific. Preset globali
# (is_preset_global=True) sono read-only.

_ENTITY_MAP = {
    "packages":         Package,
    "containers":       Container,
    "video_codecs":     VideoCodec,
    "audio_codecs":     AudioCodec,
    "channel_configs":  AudioChannelConfig,
    "mix_types":        AudioMixType,
    "mix_standards":    MixStandard,
    "resolutions":      Resolution,
    "frame_rates":      FrameRate,
}

# Campi base presenti su tutti i modelli
_BASE_FIELDS = {"name", "description", "sort_order", "is_active", "is_preset_global"}

# Campi specifici per entity (oltre _BASE_FIELDS): per validazione + serializzazione
_EXTRA_FIELDS = {
    "packages":        ["typical_use", "structure_desc"],
    "containers":      ["extension", "op_pattern", "is_image_sequence", "media_kind"],
    "video_codecs":    ["family", "profile_flavor", "typical_use", "typical_bitrate", "is_intermediate"],
    "audio_codecs":    ["family", "is_lossless"],
    "channel_configs": ["channel_count", "spec_string", "is_immersive"],
    "mix_types":       ["short_label"],
    "mix_standards":   ["family", "loudness_target_lufs", "true_peak_max_dbtp", "spl_reference_dbc", "standard_ref"],
    "resolutions":     ["width", "height", "framing_aspect", "family"],
    "frame_rates":     ["fps", "is_drop_frame", "is_ntsc_family"],
}


def _serialize_taxonomy(rec, kind: str) -> dict:
    """Serializza un record taxonomy con tutti i campi base + extra."""
    out = {f: getattr(rec, f, None) for f in _BASE_FIELDS}
    out["id"] = rec.id
    out["tenant_id"] = rec.tenant_id
    for f in _EXTRA_FIELDS.get(kind, []):
        out[f] = getattr(rec, f, None)
    return out


def _coerce_field(model_cls, field_name: str, raw_value: str):
    """Convert form string a tipo SQLAlchemy column atteso. None se vuoto."""
    if raw_value is None:
        return None
    s = raw_value.strip() if isinstance(raw_value, str) else raw_value
    if isinstance(s, str) and s == "":
        return None
    col = model_cls.__table__.c.get(field_name)
    if col is None:
        return s
    try:
        py_type = col.type.python_type
    except (NotImplementedError, AttributeError):
        return s
    if py_type is bool:
        if isinstance(s, bool):
            return s
        return str(s).strip().lower() in ("true", "1", "yes", "on", "y", "si")
    if py_type is int:
        try: return int(s)
        except (ValueError, TypeError): return None
    if py_type is float:
        try: return float(s)
        except (ValueError, TypeError): return None
    return str(s)


@router.get("/delivery-taxonomy/api/{kind}")
async def list_taxonomy_entity(kind: str, db: Session = Depends(get_db)):
    """Lista record di una entity taxonomy (preset globali + tenant-owned attivi)."""
    Model = _ENTITY_MAP.get(kind)
    if not Model:
        raise HTTPException(404, f"Entity '{kind}' non valida. Disponibili: {list(_ENTITY_MAP)}")
    rows = (
        db.query(Model)
        .filter(or_(Model.tenant_id == current_tenant_id(), Model.tenant_id.is_(None)))
        .order_by(Model.is_preset_global.desc(), Model.sort_order, Model.id)
        .all()
    )
    return {"entity": kind, "items": [_serialize_taxonomy(r, kind) for r in rows]}


@router.post("/delivery-taxonomy/api/{kind}", dependencies=[RequireEdit])
async def create_taxonomy_entity(
    kind: str, request: Request, db: Session = Depends(get_db),
):
    """Crea un record custom tenant-owned per la entity. Form: name (obblig) +
    tutti i campi extra applicabili come stringa."""
    Model = _ENTITY_MAP.get(kind)
    if not Model:
        raise HTTPException(404, f"Entity '{kind}' non valida")
    form = await request.form()
    name = (form.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name obbligatorio")
    # Verifica unicità per tenant
    exists = db.query(Model).filter(
        Model.tenant_id == current_tenant_id(),
        Model.name == name,
    ).first()
    if exists:
        raise HTTPException(400, f"name '{name}' già esistente per questo tenant")
    kwargs = {"tenant_id": current_tenant_id(), "name": name, "is_preset_global": False}
    for f in _EXTRA_FIELDS.get(kind, []) + ["description", "sort_order"]:
        if f in form:
            kwargs[f] = _coerce_field(Model, f, form.get(f))
    rec = Model(**kwargs)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return _serialize_taxonomy(rec, kind)


@router.put("/delivery-taxonomy/api/{kind}/{rec_id}", dependencies=[RequireEdit])
async def update_taxonomy_entity(
    kind: str, rec_id: int, request: Request, db: Session = Depends(get_db),
):
    """Update record taxonomy. Read-only su preset globali."""
    Model = _ENTITY_MAP.get(kind)
    if not Model:
        raise HTTPException(404, f"Entity '{kind}' non valida")
    rec = db.query(Model).filter(Model.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "Record non trovato")
    if rec.is_preset_global:
        raise HTTPException(403, "Preset globale è read-only. Crea un override custom.")
    if rec.tenant_id != current_tenant_id():
        raise HTTPException(403, "Record di altro tenant")
    form = await request.form()
    for f in ["name", "description", "sort_order", "is_active"] + _EXTRA_FIELDS.get(kind, []):
        if f in form:
            setattr(rec, f, _coerce_field(Model, f, form.get(f)))
    db.commit()
    db.refresh(rec)
    return _serialize_taxonomy(rec, kind)


@router.delete("/delivery-taxonomy/api/{kind}/{rec_id}", dependencies=[RequireEdit])
async def delete_taxonomy_entity(
    kind: str, rec_id: int, db: Session = Depends(get_db),
):
    """Soft-delete (is_active=False). Read-only su preset globali."""
    Model = _ENTITY_MAP.get(kind)
    if not Model:
        raise HTTPException(404, f"Entity '{kind}' non valida")
    rec = db.query(Model).filter(Model.id == rec_id).first()
    if not rec:
        raise HTTPException(404, "Record non trovato")
    if rec.is_preset_global:
        raise HTTPException(403, "Preset globale non eliminabile")
    if rec.tenant_id != current_tenant_id():
        raise HTTPException(403, "Record di altro tenant")
    rec.is_active = False
    db.commit()
    return {"ok": True, "id": rec_id}


@router.get("/delivery-taxonomy/api/export.json", dependencies=[RequireEdit])
async def export_taxonomy(db: Session = Depends(get_db)):
    """Esporta TUTTA la taxonomy custom del tenant (no preset globali) come JSON."""
    out = {"tenant_id": current_tenant_id(), "exported_at": None, "entities": {}}
    from datetime import datetime as _dt
    out["exported_at"] = _dt.utcnow().isoformat()
    for kind, Model in _ENTITY_MAP.items():
        rows = (
            db.query(Model)
            .filter(Model.tenant_id == current_tenant_id())
            .order_by(Model.sort_order, Model.id)
            .all()
        )
        out["entities"][kind] = [_serialize_taxonomy(r, kind) for r in rows]
    return out


@router.post("/delivery-taxonomy/api/import", dependencies=[RequireEdit])
async def import_taxonomy(request: Request, db: Session = Depends(get_db)):
    """Importa taxonomy JSON (formato export). Crea solo record nuovi (name unique).
    Body: `{"entities": {"packages": [...], ...}}`"""
    body = await request.json()
    entities = body.get("entities") or {}
    stats = {"created": 0, "skipped": 0}
    for kind, items in entities.items():
        Model = _ENTITY_MAP.get(kind)
        if not Model:
            continue
        existing = {r.name for r in db.query(Model.name).filter(
            Model.tenant_id == current_tenant_id()
        ).all()}
        for it in items or []:
            name = (it.get("name") or "").strip()
            if not name or name in existing:
                stats["skipped"] += 1
                continue
            kwargs = {"tenant_id": current_tenant_id(), "name": name, "is_preset_global": False}
            for f in _EXTRA_FIELDS.get(kind, []) + ["description", "sort_order"]:
                if f in it and it[f] is not None:
                    kwargs[f] = it[f]
            db.add(Model(**kwargs))
            stats["created"] += 1
    db.commit()
    return {"ok": True, **stats}


# ── AI extract (re-parse capitolato → materialize items) ────

@router.post("/delivery-templates/api/{tid}/items/ai-extract", dependencies=[RequireEdit])
async def ai_extract_items(tid: int, request: Request, db: Session = Depends(get_db)):
    """Esegue parse_delivery_items_v2 sul source_document del template + materialize.
    Idempotente per (name, template). Ritorna count saved/skipped."""
    tpl = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == tid,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not tpl:
        raise HTTPException(404, "DeliveryTemplate non trovato")
    if not tpl.source_document_name:
        raise HTTPException(400, "Template senza source_document_name (creato manualmente?). "
                                  "Aggiungi un capitolato in docs/capitolati_esempio/ e rilancia.")
    proj_root = Path(__file__).resolve().parents[2]
    fpath = (proj_root / "docs" / "capitolati_esempio" / tpl.source_document_name).resolve()
    samples_dir = (proj_root / "docs" / "capitolati_esempio").resolve()
    try:
        fpath.relative_to(samples_dir)
    except ValueError:
        raise HTTPException(400, "filename fuori scope")
    if not fpath.is_file():
        raise HTTPException(404, f"Capitolato sorgente non trovato: {tpl.source_document_name}")
    # Provider AI per-utente
    from app.services.ai_provider import get_provider_for_user, get_provider
    from app.services.deliverables_parser import extract_text_from_file
    from app.services.delivery_items_parser import parse_delivery_items_v2, materialize_items
    user = current_user_optional(request)
    provider = get_provider_for_user(user.id, db) if user else None
    if not provider:
        provider = get_provider()
    if not provider:
        raise HTTPException(503, "AI provider non configurato.")
    content = fpath.read_bytes()
    if not content:
        raise HTTPException(400, "Capitolato vuoto.")
    text = extract_text_from_file(content, tpl.source_document_name)
    if not text or len(text.strip()) < 20:
        raise HTTPException(400, "Estrazione testo fallita (PDF image-only?).")
    parsed = parse_delivery_items_v2(text, db, tenant_id=current_tenant_id(), provider=provider)
    if not parsed:
        diag = getattr(provider, "last_extract_diag", None) or {}
        raise HTTPException(503, f"Parser AI failed. Diag: {diag.get('error') or 'no detail'}")
    saved, skipped = materialize_items(db, tid, parsed, tenant_id=current_tenant_id())
    return {
        "ok": True,
        "items_extracted": len(parsed.get("items") or []),
        "saved": saved,
        "skipped": skipped,
        "pass1_categories": parsed.get("pass1_categories") or [],
    }


# ── AudioConfigPreset (v3.5.0-alpha.172.127) ──────────────────

def _serialize_preset(p) -> dict:
    return {
        "id": p.id, "delivery_template_id": p.delivery_template_id,
        "code": p.code, "name": p.name, "description": p.description,
        "track_layout": p.track_layout or [], "sort_order": p.sort_order,
        "is_active": p.is_active,
    }


@router.get("/delivery-templates/api/{tid}/audio-presets")
async def list_audio_presets(tid: int, db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    rows = (db.query(AudioConfigPreset)
            .filter(AudioConfigPreset.delivery_template_id == tid,
                    AudioConfigPreset.tenant_id == current_tenant_id(),
                    AudioConfigPreset.is_active == True)  # noqa: E712
            .order_by(AudioConfigPreset.sort_order, AudioConfigPreset.code).all())
    return [_serialize_preset(p) for p in rows]


@router.post("/delivery-templates/api/{tid}/audio-presets", dependencies=[RequireEdit])
async def create_audio_preset(tid: int, code: str = Form(...), name: str = Form(...),
                              description: Optional[str] = Form(None),
                              track_layout_json: Optional[str] = Form(None),
                              db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    tpl = db.query(DeliveryTemplate).filter(
        DeliveryTemplate.id == tid,
        DeliveryTemplate.tenant_id == current_tenant_id(),
    ).first()
    if not tpl:
        raise HTTPException(404, "DeliveryTemplate non trovato")
    track_layout = []
    if track_layout_json and track_layout_json.strip():
        try:
            v = json.loads(track_layout_json)
            if isinstance(v, list):
                track_layout = v
        except json.JSONDecodeError:
            pass
    p = AudioConfigPreset(
        tenant_id=current_tenant_id(), delivery_template_id=tid,
        code=code.strip(), name=name.strip(), description=description,
        track_layout=track_layout,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serialize_preset(p)


@router.put("/delivery-audio-presets/api/{pid}", dependencies=[RequireEdit])
async def update_audio_preset(pid: int, code: Optional[str] = Form(None),
                              name: Optional[str] = Form(None),
                              description: Optional[str] = Form(None),
                              track_layout_json: Optional[str] = Form(None),
                              db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.id == pid,
        AudioConfigPreset.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "preset non trovato")
    if code is not None:
        p.code = code.strip()
    if name is not None:
        p.name = name.strip()
    if description is not None:
        p.description = description
    if track_layout_json is not None:
        try:
            v = json.loads(track_layout_json) if track_layout_json.strip() else []
            p.track_layout = v if isinstance(v, list) else []
        except json.JSONDecodeError:
            p.track_layout = []
    db.commit()
    return _serialize_preset(p)


@router.delete("/delivery-audio-presets/api/{pid}", dependencies=[RequireEdit])
async def delete_audio_preset(pid: int, db: Session = Depends(get_db)):
    from app.models.models import AudioConfigPreset
    p = db.query(AudioConfigPreset).filter(
        AudioConfigPreset.id == pid,
        AudioConfigPreset.tenant_id == current_tenant_id()).first()
    if not p:
        raise HTTPException(404, "preset non trovato")
    p.is_active = False  # soft-delete
    db.commit()
    return {"ok": True}
