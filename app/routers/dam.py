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
    apply_watermark_pdf, is_pdf_mime,
)
from fastapi.responses import Response
from app.services.rbac import requires_permission, current_user_optional, is_admin
from app.services.project_access import (
    user_can_access_asset, accessible_project_ids, log_asset_access,
    check_project_ip_allowlist, check_project_mfa_required,
    user_can_access_project,
)
from app.context import current_tenant_id
import os

router = APIRouter(prefix="/dam", tags=["dam"])

# v3.5.0-alpha.66.15.2 — tenant scope (R1)
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
        Asset.tenant_id == current_tenant_id(),
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
        Asset.tenant_id == current_tenant_id(),
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


# v3.5.0-alpha.172.92 (Bundle H3) — Metadata tecnici estratti dal file +
# delivery linked status (deliverable + qc_substatus). Read-only.

@router.get("/api/assets/{asset_id}/metadata")
async def get_asset_metadata(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Estrae metadata tecnici dal file Asset via ffprobe / Pillow.
    Idempotente: re-invocazione = ri-estrazione (no cache per ora).
    Output shape vedi `app.services.asset_metadata.extract_asset_metadata`.
    """
    from app.services.asset_metadata import extract_asset_metadata
    a = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    # v3.5.0-alpha.172.147 (audit TPN gap #1) — access check: i metadata
    # tecnici (codec/risoluzione/durata) sono informazione sensibile su un
    # asset compartimentalizzato. Senza questo check chiunque autenticato
    # poteva leggerli per asset di progetti non suoi.
    user = current_user_optional(request)
    if not user_can_access_asset(user, a, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="metadata read denied")
        raise HTTPException(403, "Accesso negato (TPN compartimentalizzazione)")
    if not a.file_path:
        return {"asset_id": asset_id, "tool": "none",
                "errors": ["asset senza file_path"],
                "video": None, "audio": [], "container": None}
    # S3 paths: non possiamo leggere local file → skip
    if a.file_path.startswith("s3://"):
        return {"asset_id": asset_id, "tool": "none",
                "errors": ["file su S3, metadata extraction non supportata"],
                "video": None, "audio": [], "container": None}
    meta = extract_asset_metadata(a.file_path, a.mime_type)
    meta["asset_id"] = asset_id
    meta["filename"] = a.original_name
    meta["mime_type"] = a.mime_type
    meta["file_size"] = a.file_size
    return meta


@router.get("/api/assets/{asset_id}/delivery-info")
async def get_asset_delivery_info(
    asset_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Restituisce delivery context dell'asset: deliverable linkati,
    status main + qc_substatus, project/job. Read-only — editing su
    /planning HUB (Bundle J)."""
    from app.models import (
        JobDeliverable, DeliverableAsset, Job, Project,
        DeliverableStatus, AssetStatus,
    )
    a = db.query(Asset).filter(
        Asset.id == asset_id,
        Asset.tenant_id == current_tenant_id(),
    ).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    # v3.5.0-alpha.172.147 (audit TPN gap #1) — access check
    user = current_user_optional(request)
    if not user_can_access_asset(user, a, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="delivery-info read denied")
        raise HTTPException(403, "Accesso negato (TPN compartimentalizzazione)")

    deliverables = []
    # Primary FK (legacy): job_deliverable_id
    if a.job_deliverable_id:
        d = db.query(JobDeliverable).filter(
            JobDeliverable.id == a.job_deliverable_id,
            JobDeliverable.tenant_id == current_tenant_id(),
        ).first()
        if d:
            deliverables.append(_serialize_deliv_for_asset(db, d, source="primary_fk"))
    # M:N pivot DeliverableAsset
    links = db.query(DeliverableAsset).filter(
        DeliverableAsset.asset_id == asset_id,
        DeliverableAsset.tenant_id == current_tenant_id(),
    ).all()
    seen = {d["id"] for d in deliverables}
    for link in links:
        d = db.query(JobDeliverable).filter(
            JobDeliverable.id == link.job_deliverable_id,
            JobDeliverable.tenant_id == current_tenant_id(),
        ).first()
        if d and d.id not in seen:
            deliverables.append(_serialize_deliv_for_asset(db, d, source=link.source or "manual"))
            seen.add(d.id)

    return {
        "asset_id": asset_id,
        "asset_status": a.status.value if a.status else "planned",
        "is_internal_archive": a.is_internal_archive,
        "is_delivered_external": a.is_delivered_external,
        "delivered_at": a.delivered_at.isoformat() + "Z" if a.delivered_at else None,
        "delivered_to": a.delivered_to,
        "deliverables": deliverables,
        "parent_asset_id": a.parent_asset_id,
        "version": a.version,
    }


def _serialize_deliv_for_asset(db, d, source="manual"):
    """Helper: serializza deliverable minimo per asset delivery-info."""
    from app.models import Job, Project
    job = db.query(Job).filter(Job.id == d.job_id).first()
    project = db.query(Project).filter(Project.id == job.project_id).first() if job and job.project_id else None
    return {
        "id": d.id,
        "name": d.name,
        "status": d.status.value if d.status else "planned",
        "qc_substatus": d.qc_substatus.value if d.qc_substatus else None,
        "target_delivery_date": d.target_delivery_date.isoformat() if d.target_delivery_date else None,
        "delivered_date": d.delivered_date.isoformat() if d.delivered_date else None,
        "link_source": source,
        "job_id": d.job_id,
        "job_code": job.code if job else None,
        "job_title": job.title if job else None,
        "project_id": project.id if project else None,
        "project_code": project.code if project else None,
        "project_title": project.title if project else None,
    }


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
        Asset.id == asset_id, Asset.tenant_id == current_tenant_id()
    ).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    # v3.5.0-alpha.110 TPN: check user può accedere al PROGETTO target
    # (non basta essere admin tenant; user deve avere grant sul project
    # per TPN compart). Skip per admin elevati globali.
    if not is_admin(user) and not user_can_access_project(user, project_id, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=project_id, request=request,
                         extra="assign target project not in user grants")
        raise HTTPException(403, "Non hai accesso al progetto target (TPN)")
    a.project_id = project_id
    log_asset_access(db, user=user, action=AssetAccessAction.update,
                     asset_id=asset_id, project_id=project_id, request=request,
                     extra="assigned to project")
    db.commit()
    return {"ok": True, "asset_id": asset_id, "project_id": project_id}


@router.post("/api/assets/upload", dependencies=[RequireEditDam])
async def upload_asset(
    request: Request,
    file: UploadFile = File(...),
    job_id: Optional[int] = Form(None),
    project_id: Optional[int] = Form(None),
    uploaded_by: Optional[int] = Form(None),  # anti-spoof: ignorato se user auth (vedi sotto)
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
            Job.id == job_id, Job.tenant_id == current_tenant_id()
        ).first()
        if job:
            project_id = job.project_id

    # v3.5.0-alpha.110 TPN: check user può uploadare al project specificato
    user = current_user_optional(request)
    if project_id and not is_admin(user) and not user_can_access_project(user, project_id, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         project_id=project_id, request=request,
                         extra="upload target project not in user grants")
        raise HTTPException(403, "Non hai accesso al progetto target (TPN)")

    # v3.5.0-alpha.172.147 (audit TPN gap #2) — MFA required sul progetto
    # vale anche in upload (prima solo download era gated).
    if not check_project_mfa_required(user, project_id, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         project_id=project_id, request=request,
                         extra="upload blocked: project requires MFA")
        raise HTTPException(403, "Progetto richiede MFA. Configura MFA in /settings → 🔒 MFA TOTP")

    # v3.5.0-alpha.172.147 (audit TPN gap #5) — uploaded_by deriva
    # dall'utente AUTENTICATO, non dal form: il campo client era
    # falsificabile (audit trail/attribuzione inaffidabile). Fallback al
    # form solo se non c'è sessione (path non autenticati / script seed).
    effective_uploaded_by = user.id if user else (uploaded_by or 1)

    asset = Asset(
        tenant_id=current_tenant_id(),
        filename=filename,
        original_name=file.filename,
        file_path=file_path,
        thumbnail_path=thumbnail_path,
        asset_type=asset_type,
        mime_type=mime_type,
        file_size=len(file_bytes),
        job_id=job_id,
        project_id=project_id,
        uploaded_by=effective_uploaded_by,
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
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == current_tenant_id()).first()
    # v3.5.0-alpha.110 — Asset.file_path può essere "s3://bucket/key" se
    # storage_backend=s3. In quel caso non c'è file locale → check via storage.
    is_s3 = a and a.file_path and a.file_path.startswith("s3://")
    if not a:
        raise HTTPException(404, "Asset non trovato")
    if not is_s3 and not os.path.exists(a.file_path):
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
    # v3.5.0-alpha.172.147 (audit TPN gap #4) — watermark anche su PDF
    # (capitolati, allegati, delivery note). Non-admin: forzato (no bypass
    # via ?watermark=0). Video/DCP/altri binari restano fuori scope (serve
    # ffmpeg/transcode) ma sono comunque access-gated + loggati sopra.
    force_wm = not is_admin(user)
    if (watermark or force_wm) and not is_s3 and is_pdf_mime(a.mime_type):
        wm_bytes = apply_watermark_pdf(
            a.file_path,
            user_email=(user.email if user else None),
            extra=f"asset:{a.id}",
        )
        if wm_bytes:
            fname = (a.original_name.rsplit(".", 1)[0]
                     + "_wm.pdf") if "." in a.original_name else a.original_name + "_wm.pdf"
            return Response(content=wm_bytes, media_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    # v3.5.0-alpha.110 — Se file su S3 → redirect a presigned URL.
    if is_s3:
        try:
            from app.services.storage import get_storage_for_project
            from app.models import Project as _P
            from fastapi.responses import RedirectResponse
            proj = (db.query(_P).filter(_P.id == a.project_id).first()
                    if a.project_id else None)
            storage = get_storage_for_project(proj, fallback_tenant_id=current_tenant_id())
            # Estrai key da "s3://bucket/prefix/key" → key relativa
            url = storage.presigned_url(_s3_key_from_path(a.file_path, storage))
            if url:
                return RedirectResponse(url, status_code=302)
            raise HTTPException(503, "Presigned URL S3 non disponibile")
        except Exception as e:
            raise HTTPException(503, f"S3 access error: {e}")
    # Non-image o watermark disabilitato by admin
    return FileResponse(a.file_path, filename=a.original_name, media_type=a.mime_type)


def _s3_key_from_path(file_path: str, storage) -> str:
    """v3.5.0-alpha.110 — Estrae key relativa da `s3://bucket/prefix/...`
    rimuovendo `bucket/prefix/`. Storage.presigned_url aggiunge prefix da sé.
    """
    # file_path = "s3://bucket/prefix/key/sub.jpg"
    # Vogliamo "key/sub.jpg" (la prefix verrà ri-aggiunta da S3Backend._key)
    rest = file_path[5:]  # rimuovi "s3://"
    parts = rest.split("/", 1)
    if len(parts) < 2:
        return rest
    after_bucket = parts[1]
    prefix = getattr(storage, "prefix", "")
    if prefix and after_bucket.startswith(prefix + "/"):
        return after_bucket[len(prefix) + 1:]
    return after_bucket


@router.get("/thumbnail/{asset_id}")
async def get_thumbnail(asset_id: int, request: Request, db: Session = Depends(get_db)):
    user = current_user_optional(request)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == current_tenant_id()).first()
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
    secure: int = 1,
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.172.147 (audit TPN gap #3) — secure delete è ora il
    DEFAULT (`secure=1`): DOD wipe (random 3 pass) prima di unlink, no
    recover dei dati su disco. `?secure=0` opt-out esplicito (delete veloce
    per asset non sensibili / file molto grandi)."""
    user = current_user_optional(request)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == current_tenant_id()).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    if not user_can_access_asset(user, a, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="delete denied")
        raise HTTPException(403, "Accesso negato")
    # v3.5.0-alpha.172.147 (audit TPN gap #2) — MFA required vale anche in delete
    if not check_project_mfa_required(user, a.project_id, db):
        log_asset_access(db, user=user, action=AssetAccessAction.deny,
                         asset_id=asset_id, project_id=a.project_id, request=request,
                         extra="delete blocked: project requires MFA")
        raise HTTPException(403, "Progetto richiede MFA. Configura MFA in /settings → 🔒 MFA TOTP")
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


# ── Filesystem scan generic (v3.5.0-alpha.96, #9b) ────────────────────
# Scopo: AI/utente scansiona cartella filesystem ESTERNA (NAS, disco
# cliente montato), classifica file via MIME → tipo Asset, ritorna albero
# editabile. Import bottone: registra Asset record (file_path = path
# originale, no copia). Diverso dal `physical-assets/{id}/scan-content`
# (legato a un PhysicalAsset specifico + AssetMembership).
#
# Sicurezza: path DEVE essere sotto uno dei `Tenant.fs_scan_allowed_paths`.
# Niente arbitrary FS access (lo enforced server-side anche se UI lo accetta).


def _is_path_allowed(path_str: str, allowed: Optional[list]) -> bool:
    """v3.5.0-alpha.96 — Whitelist filesystem scan: path richiesto deve
    essere uguale o sotto uno dei prefissi in allowed_paths.
    Resolve a path reali per evitare ../ traversal."""
    if not allowed:
        return False
    try:
        from pathlib import Path as _P
        target = _P(path_str).resolve(strict=False)
    except (OSError, ValueError):
        return False
    for prefix_str in allowed:
        if not prefix_str:
            continue
        try:
            from pathlib import Path as _P
            prefix = _P(prefix_str).resolve(strict=False)
            # Target deve essere prefix o suo discendente
            try:
                target.relative_to(prefix)
                return True
            except ValueError:
                continue
        except (OSError, ValueError):
            continue
    return False


@router.post("/api/fs-scan", dependencies=[RequireEditDam])
async def fs_scan(
    request: Request,
    path: str = Form(...),
    compute_checksum: int = Form(0),
    max_depth: int = Form(8),
    max_files: int = Form(2000),
    project_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.96 — Walk filesystem path autorizzato + classifica
    file per tipo. NO DB write — solo preview JSON.

    v3.5.0-alpha.105 — Whitelist composta:
    - tenant.fs_scan_allowed_paths (cross-progetto, admin tenant)
    - project.fs_scan_paths (override per-progetto, se project_id valorizzato)
    Se project_id è dato, l'utente DEVE avere access al project + path
    DEVE essere nella whitelist del project (per TPN strict).
    """
    from app.services.fs_scan import walk_filesystem
    from app.models import Tenant, Project
    tenant = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    tenant_paths = (tenant.fs_scan_allowed_paths if tenant else None) or []
    project_paths = []
    if project_id:
        p = db.query(Project).filter(
            Project.id == project_id,
            Project.tenant_id == current_tenant_id(),
        ).first()
        if not p:
            raise HTTPException(404, f"Project {project_id} non trovato nel tenant")
        project_paths = p.fs_scan_paths or []
        # v3.5.0-alpha.105 TPN strict: se Project ha lista non vuota, USA
        # SOLO quella (compartimentazione stagna). Tenant-level resta
        # accessibile solo se Project.fs_scan_paths è null/vuota.
        allowed = project_paths if project_paths else tenant_paths
    else:
        allowed = tenant_paths
    if not _is_path_allowed(path, allowed):
        raise HTTPException(
            403,
            "Path non autorizzato. " + (
                f"Aggiungilo a Project.fs_scan_paths (id={project_id})"
                if project_id and project_paths else
                "Aggiungilo a tenant.fs_scan_allowed_paths via /settings → Storage."
            )
        )
    result = walk_filesystem(
        path, compute_checksum=bool(compute_checksum),
        max_depth=max(1, min(int(max_depth), 16)),
        max_files=max(1, min(int(max_files), 10000)),
    )
    if result.get("error"):
        raise HTTPException(400, result["error"])
    # Classifica per asset_type via MIME (riusa resolve_asset_type)
    for f in result.get("files", []):
        f["asset_type"] = resolve_asset_type(f.get("mime") or "").value
    return {
        "root": result["root"],
        "file_count": result["file_count"],
        "total_size": result["total_size"],
        "files": result["files"],
        "errors": result.get("errors", []),
        "hash_algo": result.get("algo"),
    }


@router.post("/api/fs-import", dependencies=[RequireEditDam])
async def fs_import(
    request: Request,
    base_path: str = Form(...),
    file_paths_json: str = Form(...),   # JSON array di rel_path
    project_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.96 — Registra Asset DAM per i file selezionati dalla
    scan. NON copia il contenuto: il file resta dov'è (es. su NAS), Asset
    record punta al path reale. Utente può deciderne il progetto target.
    """
    import json as _json
    from pathlib import Path as _Path
    import mimetypes
    from app.models import Tenant
    tenant = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    allowed = (tenant.fs_scan_allowed_paths if tenant else None) or []
    if not _is_path_allowed(base_path, allowed):
        raise HTTPException(403, "base_path non autorizzato")
    try:
        rel_paths = _json.loads(file_paths_json)
    except _json.JSONDecodeError as e:
        raise HTTPException(400, f"file_paths_json malformato: {e}")
    if not isinstance(rel_paths, list) or not rel_paths:
        raise HTTPException(400, "file_paths_json deve essere lista non vuota")
    base = _Path(base_path).resolve()
    user = current_user_optional(request)
    # v3.5.0-alpha.110 TPN: user deve avere accesso al project target
    if project_id and not is_admin(user) and not user_can_access_project(user, project_id, db):
        raise HTTPException(403, "Non hai accesso al progetto target (TPN)")
    uploaded_count = 0
    skipped = []
    for rel in rel_paths:
        if not isinstance(rel, str):
            continue
        full = (base / rel).resolve()
        # Re-check sicurezza: il file resolved deve essere sotto base
        try:
            full.relative_to(base)
        except ValueError:
            skipped.append({"rel": rel, "reason": "path traversal rejected"})
            continue
        if not full.exists() or not full.is_file():
            skipped.append({"rel": rel, "reason": "file not found"})
            continue
        try:
            st = full.stat()
        except OSError as e:
            skipped.append({"rel": rel, "reason": str(e)})
            continue
        mime, _ = mimetypes.guess_type(full.name)
        mime = mime or "application/octet-stream"
        a = Asset(
            tenant_id=current_tenant_id(),
            filename=full.name,
            original_name=full.name,
            file_path=str(full),  # NB: path reale, no copia
            thumbnail_path=None,
            asset_type=resolve_asset_type(mime),
            mime_type=mime,
            file_size=st.st_size,
            project_id=project_id,
            job_id=job_id,
            uploaded_by=user.id if user else 1,
            description=f"Importato da fs-scan: {rel}",
        )
        db.add(a)
        uploaded_count += 1
    db.commit()
    return {
        "ok": True,
        "imported": uploaded_count,
        "skipped": skipped,
        "skipped_count": len(skipped),
    }


@router.get("/fs-scan", response_class=HTMLResponse)
async def fs_scan_page(request: Request, db: Session = Depends(get_db)):
    """v3.5.0-alpha.96 — UI scan + import. Mostra path autorizzati,
    permette esplorazione e import selettivo come Asset DAM."""
    from app.models import Tenant
    tenant = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    allowed = (tenant.fs_scan_allowed_paths if tenant else None) or []
    from app.models import Project as _P
    projects = db.query(_P).filter(_P.tenant_id == current_tenant_id()).order_by(_P.created_at.desc()).limit(500).all()
    return _tpl().TemplateResponse(
        "pages/fs_scan.html",
        {"request": request, "allowed_paths": allowed, "projects": projects},
    )
