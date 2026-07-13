"""Router Media Library (Fase A) — browser unificato read-only asset
digitali (Asset) + fisici (PhysicalAsset). Nessuna azione mutante: le
associazioni/azioni bulk arrivano nelle fasi B/C/D.

Gate RBAC: manage_assets (retrocompat edit_planning_all) via media_gate.
Tenant-scope + visibilità TPN sono applicati dentro media_library."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.media_gate import requires_manage_assets
from app.services import media_library

router = APIRouter(prefix="/media", tags=["media"])
_Gate = Depends(requires_manage_assets())

# Chiavi filtro accettate dalla API assets (whitelist: ignora il resto).
_FILTER_KEYS = ("nature", "project_id", "client_id", "job_id", "department_id",
                "asset_type", "physical_kind", "delivery_status", "proposed_state",
                "internal_archive", "delivered_external", "linked_to_delivery",
                "volume_id", "q", "checksum",
                "tech_resolution", "tech_codec", "tech_hdr", "tech_frame_rate")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def media_page(request: Request, user=_Gate):
    from app.main import templates
    return templates.TemplateResponse(
        "pages/media_library.html",
        {"request": request, "active_page": "media"},
    )


@router.get("/api/assets")
async def media_assets(request: Request, user=_Gate, db: Session = Depends(get_db),
                       offset: int = 0, limit: int = 50):
    filters = {k: v for k, v in request.query_params.items() if k in _FILTER_KEYS and v}
    return media_library.list_assets(db, user, filters, offset=offset, limit=limit)


@router.get("/api/filters")
async def media_filters(user=_Gate, db: Session = Depends(get_db)):
    return media_library.filter_options(db, user)


@router.get("/api/asset/{nature}/{asset_id}")
async def media_asset_detail(nature: str, asset_id: int, user=_Gate,
                             db: Session = Depends(get_db)):
    if nature not in ("digital", "physical"):
        raise HTTPException(404, "natura non valida")
    d = media_library.asset_detail(db, user, nature, asset_id)
    if d is None:
        raise HTTPException(404, "Asset non trovato o non accessibile")
    return d
