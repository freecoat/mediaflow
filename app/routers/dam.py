"""Router DAM — upload, ricerca, versioning, tag.

v3.5.0-alpha.70 — TPN compliance: access control compartimentalizzato.
Ogni endpoint applica `user_can_access_asset()` o
`accessible_project_ids()` per filtrare il visibile all'user.
Tutti i tentativi (incl. negati) loggati in AssetAccessLog.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from app.database import get_db
from app.models import (
    Asset, AssetType, Tag, AssetTag, User, AssetAccessAction, Job,
)
from app.services.dam import save_upload, generate_thumbnail, resolve_asset_type, delete_asset_files
from app.services.dam_security import (
    apply_watermark_image, secure_delete_file, is_image_mime,
)
from fastapi.responses import Response
from app.services.rbac import requires_permission, current_user_optional, is_admin
from app.services.project_access import (
    user_can_access_asset, accessible_project_ids, log_asset_access,
    check_project_ip_allowlist, check_project_mfa_required,
)
from app.context import current_tenant_id
import os

router = APIRouter(prefix="/dam", tags=["dam"])

# v3.5.0-alpha.66.15.2 — tenant scope (R1)
CURRENT_TENANT = current_tenant_id()

# v3.5.0-alpha.66.16.0 — Sprint R3: gate per upload/delete asset DAM.
# Manca permesso DAM-specifico nello schema RBAC; usato `edit_planning_all`
# come fallback ragionevole (chi gestisce la pianificazione operativa
# tipicamente deve poter caricare e cancellare asset). Da rivedere se
# Matteo introdurrà `manage_assets` dedicato.
RequireEditDam = Depends(requires_permission("edit_planning_all"))


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ───────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dam_page(request: Request, db: Session = Depends(get_db)):
    # v3.5.0-alpha.70 — TPN access control. Filtro asset per progetti
    # accessibili dall'user. project_id=NULL (internal queue) visibile
    # solo a admin/manager + uploader proprio.
    user = current_user_optional(request)
    proj_ids = accessible_project_ids(user, db)
    q = db.query(Asset).filter(
        Asset.tenant_id == CURRENT_TENANT,
        Asset.parent_asset_id == None,  # noqa: E711
    )
    if is_admin(user):
        pass  # vede tutto
    else:
        filters = []
        if proj_ids:
            filters.append(Asset.project_id.in_(proj_ids))
        # Internal queue: visibile solo all'uploader
        if user:
            filters.append((Asset.project_id.is_(None)) & (Asset.uploaded_by == user.id))
        if filters:
            q = q.filter(or_(*filters))
        else:
            q = q.filter(Asset.id < 0)  # zero rows
    assets = q.order_by(Asset.created_at.desc()).limit(50).all()
    tags = db.query(Tag).all()
    return _tpl().TemplateResponse(
        "pages/dam.html", {"request": request, "assets": assets, "tags": tags}
    )


# ── Asset API ─────────────────────────────────────────────────────────

@router.get("/api/assets")
async def list_assets(
    request: Request,
    asset_type: Optional[AssetType] = None,
    job_id: Optional[int] = None,
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    tech: Optional[str] = None,
    include_internal: int = 0,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.70 — TPN access filter.
    v3.5.0-alpha.86 (S3.4) — Filtri estesi: client_id + period + tech.
    `tech` = comma-separated keyword (HDR, SDR, 2K, 4K, UHD, 24fps, 25fps...);
    match case-insensitive su original_name + description. Asset model non ha
    metadata strutturate, quindi grep su nome file/descrizione.
    """
    """v3.5.0-alpha.70 — TPN access filter.
    Solo asset di progetti accessibili dall'user + opt internal queue
    propria dell'uploader."""
    user = current_user_optional(request)
    proj_ids = accessible_project_ids(user, db)
    query = db.query(Asset).filter(
        Asset.tenant_id == CURRENT_TENANT,
        Asset.parent_asset_id == None,  # noqa: E711
    )
    if not is_admin(user):
        filters = []
        if proj_ids:
            filters.append(Asset.project_id.in_(proj_ids))
        if user and include_internal:
            filters.append((Asset.project_id.is_(None)) & (Asset.uploaded_by == user.id))
        if filters:
            query = query.filter(or_(*filters))
        else:
            query = query.filter(Asset.id < 0)
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if job_id:
        query = query.filter(Asset.job_id == job_id)
    if project_id:
        if not is_admin(user) and project_id not in proj_ids:
            log_asset_access(db, user=user, action=AssetAccessAction.deny,
                             project_id=project_id, request=request,
                             extra=f"list_assets project_id={project_id} not in grants")
            raise HTTPException(403, "Accesso al progetto non autorizzato")
        query = query.filter(Asset.project_id == project_id)
    if q:
        query = query.filter(Asset.original_name.ilike(f"%{q}%"))
    if tag:
        # v3.5.0-alpha.88 — tag ora accetta CSV per multi-select (es. tag=raw,finale).
        # Match ANY: l'asset ha almeno uno dei tag richiesti.
        # v3.5.0-alpha.91 audit fix P1: uso EXISTS subquery invece di INNER JOIN
        # per evitare righe duplicate (1 asset × N tag matching = N righe).
        tag_names = [t.strip() for t in tag.split(",") if t.strip()]
        if tag_names:
            from sqlalchemy import exists
            tag_exists = (
                db.query(AssetTag.asset_id)
                .join(Tag, AssetTag.tag_id == Tag.id)
                .filter(AssetTag.asset_id == Asset.id, Tag.name.in_(tag_names))
                .exists()
            )
            query = query.filter(tag_exists)
    # v3.5.0-alpha.86 (S3.4) — client_id + period + tech filters
    if client_id:
        from app.models import Project as _Project
        query = query.join(_Project, Asset.project_id == _Project.id).filter(_Project.client_id == client_id)
    if from_date:
        try:
            from datetime import date as _date
            d = _date.fromisoformat(from_date)
            query = query.filter(Asset.created_at >= d)
        except ValueError:
            pass
    if to_date:
        try:
            from datetime import date as _date, timedelta as _td
            d = _date.fromisoformat(to_date) + _td(days=1)
            query = query.filter(Asset.created_at < d)
        except ValueError:
            pass
    if tech:
        # Match qualunque keyword in original_name OR description (case insensitive)
        keywords = [k.strip() for k in tech.split(",") if k.strip()]
        if keywords:
            conds = []
            for kw in keywords:
                pat = f"%{kw}%"
                conds.append(Asset.original_name.ilike(pat) | Asset.description.ilike(pat))
            from sqlalchemy import or_ as _or
            query = query.filter(_or(*conds))
    # v3.5.0-alpha.93 — limit opzionale per UI compatte (modal Shipment).
    _q = query.order_by(Asset.created_at.desc())
    if limit and limit > 0:
        _q = _q.limit(min(limit, 1000))
    assets = _q.all()
    return [
        {
            "id": a.id,
            "original_name": a.original_name,
            "asset_type": a.asset_type,
            "mime_type": a.mime_type,
            "file_size": a.file_size,
            "thumbnail_url": f"/dam/thumbnail/{a.id}" if a.thumbnail_path else None,
            "download_url": f"/dam/download/{a.id}",
            "tags": [t.name for t in a.tags],
            "job_id": a.job_id,
            "project_id": a.project_id,
            "is_internal": a.project_id is None,
            "version": a.version,
            "created_at": a.created_at.isoformat(),
        }
        for a in assets
    ]


@router.post("/api/assets/{asset_id}/assign-project", dependencies=[RequireEditDam])
async def assign_asset_to_project(
    asset_id: int,
    request: Request,
    project_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.70 — Sposta un asset dall'internal queue a un progetto
    (esce dal compartimento internal e diventa visibile alle risorse del
    progetto). Solo admin/manager/elevated."""
    user = current_user_optional(request)
    if not is_admin(user):
        # Only admin per ora — più avanti relaxare con permission gate
        raise HTTPException(403, "Solo admin/manager possono assegnare asset")
    a = db.query(Asset).filter(
        Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT
    ).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    a.project_id = project_id
    log_asset_access(db, user=user, action=AssetAccessAction.update,
                     asset_id=asset_id, project_id=project_id, request=request,
                     extra="assigned to project")
    return {"ok": True, "asset_id": asset_id, "project_id": project_id}


@router.post("/api/assets/upload", dependencies=[RequireEditDam])
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    job_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    uploaded_by: int = Form(...),
    description: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # CSV di tag
    db: Session = Depends(get_db),
):
    if file.size and file.size > 200 * 1024 * 1024:
        raise HTTPException(413, "File troppo grande (max 200 MB)")

    file_bytes = await file.read()
    filename, file_path, mime_type = save_upload(file_bytes, file.filename)
    thumbnail_path = generate_thumbnail(file_path, mime_type)
    asset_type = resolve_asset_type(mime_type)

    # v3.5.0-alpha.70 — Auto-resolve project_id da job_id se non passato
    if project_id is None and job_id is not None:
        job = db.query(Job).filter(
            Job.id == job_id, Job.tenant_id == CURRENT_TENANT
        ).first()
        if job:
            project_id = job.project_id

    asset = Asset(
        tenant_id=CURRENT_TENANT,
        filename=filename,
        original_name=file.filename,
        file_path=file_path,
        thumbnail_path=thumbnail_path,
        asset_type=asset_type,
        mime_type=mime_type,
        file_size=len(file_bytes),
        job_id=job_id,
        project_id=project_id,
        uploaded_by=uploaded_by,
        description=description,
    )
    db.add(asset)
    db.flush()   # prende l'id prima del commit

    # Tag
    if tags:
        for tag_name in [t.strip() for t in tags.split(",") if t.strip()]:
            tag_obj = db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag_obj:
                tag_obj = Tag(name=tag_name)
                db.add(tag_obj)
                db.flush()
            db.add(AssetTag(asset_id=asset.id, tag_id=tag_obj.id))

    db.flush()
    log_asset_access(
        db, user=current_user_optional(request), action=AssetAccessAction.upload,
        asset_id=asset.id, project_id=asset.project_id, request=request,
        commit=False,
    )
    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "filename": asset.filename, "asset_type": asset.asset_type,
            "project_id": asset.project_id, "is_internal": asset.project_id is None}


@router.get("/download/{asset_id}")
async def download_asset(
    asset_id: int,
    request: Request,
    watermark: int = 1,  # v3.5.0-alpha.70.2: default ON per immagini
    db: Session = Depends(get_db),
):
    user = current_user_optional(request)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT).first()
    if not a or not os.path.exists(a.file_path):
        raise HTTPException(404, "Asset non trovato")
    # v3.5.0-alpha.70 — TPN access check
    if not user_can_access_asset(user, a, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="download denied")
        raise HTTPException(403, "Accesso negato (TPN compartimentalizzazione)")
    # v3.5.0-alpha.70.3 — IP allowlist per progetto
    if not check_project_ip_allowlist(a.project_id, request, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="ip allowlist mismatch")
        raise HTTPException(403, "IP non autorizzato per questo progetto (TPN allowlist)")
    # v3.5.0-alpha.70.4 — MFA required check
    if not check_project_mfa_required(user, a.project_id, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="mfa not enabled on user, project requires MFA")
        raise HTTPException(403, "Progetto richiede MFA. Configura MFA in /settings → 🔒 MFA TOTP")
    log_asset_access(db, user=user, action=AssetAccessAction.download,
                     asset_id=asset_id, project_id=a.project_id, request=request,
                     extra=f"watermark={'on' if watermark else 'off'}")
    # v3.5.0-alpha.70.2 — Watermark immagini. Admin può disabilitare con
    # ?watermark=0 (es. per esporto pulito a fini di archivio). Altri:
    # forzato ON (sicurezza non bypassabile da client).
    if watermark and is_image_mime(a.mime_type):
        if not is_admin(user) or watermark == 1:
            wm_bytes = apply_watermark_image(
                a.file_path,
                user_email=(user.email if user else None),
                extra=f"asset:{a.id}",
            )
            if wm_bytes:
                # Forced .jpg output (watermark sempre JPEG)
                fname = (a.original_name.rsplit(".", 1)[0]
                         + "_wm.jpg") if "." in a.original_name else a.original_name + "_wm.jpg"
                return Response(content=wm_bytes, media_type="image/jpeg",
                                headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    # Non-image o watermark disabilitato by admin
    return FileResponse(a.file_path, filename=a.original_name, media_type=a.mime_type)


@router.get("/thumbnail/{asset_id}")
async def get_thumbnail(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT).first()
    if not a or not a.thumbnail_path or not os.path.exists(a.thumbnail_path):
        raise HTTPException(404, "Thumbnail non disponibile")
    # v3.5.0-alpha.70 — TPN access check (no log per thumbnail per non
    # spam-mare il log con view passive)
    if not user_can_access_asset(user, a, db):
        raise HTTPException(403, "Accesso negato")
    return FileResponse(a.thumbnail_path, media_type="image/jpeg")


@router.delete("/api/assets/{asset_id}", dependencies=[RequireEditDam])
async def delete_asset(
    asset_id: int, request: Request,
    secure: int = 0,
    db: Session = Depends(get_db),
):
    """`secure=1` → DOD wipe (random 3 pass) prima di unlink. Più lento
    ma garantisce no-recover dei dati su disco (TPN compliance)."""
    user = current_user_optional(request)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    if not user_can_access_asset(user, a, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="delete denied")
        raise HTTPException(403, "Accesso negato")
    # Log delete BEFORE actual deletion (asset_id riferimento storico)
    log_asset_access(db, user=user, action=AssetAccessAction.delete,
                     asset_id=asset_id, project_id=a.project_id, request=request,
                     extra=f"original_name={a.original_name} secure={bool(secure)}",
                     commit=False)
    if secure:
        # v3.5.0-alpha.70.2 — Secure delete DOD-style. Skip thumbnail
        # (non sensibile, ma anche scrubbed via standard unlink).
        secure_delete_file(a.file_path)
        if a.thumbnail_path:
            secure_delete_file(a.thumbnail_path)
    else:
        delete_asset_files(a.file_path, a.thumbnail_path)
    db.delete(a)
    db.commit()
    return {"ok": True, "secure": bool(secure)}


# ── Tag API ───────────────────────────────────────────────────────────

@router.get("/api/tags")
async def list_tags(db: Session = Depends(get_db)):
    return db.query(Tag).all()
