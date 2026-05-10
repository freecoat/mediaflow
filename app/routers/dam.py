"""Router DAM — upload, ricerca, versioning, tag."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Asset, AssetType, Tag, AssetTag, User
from app.services.dam import save_upload, generate_thumbnail, resolve_asset_type, delete_asset_files
from app.services.rbac import requires_permission
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
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    assets = db.query(Asset).filter(
        Asset.tenant_id == CURRENT_TENANT,
        Asset.parent_asset_id == None,
    ).order_by(Asset.created_at.desc()).limit(50).all()
    tags = db.query(Tag).all()
    return _tpl().TemplateResponse(
        "pages/dam.html", {"request": request, "assets": assets, "tags": tags}
    )


# ── Asset API ─────────────────────────────────────────────────────────

@router.get("/api/assets")
async def list_assets(
    asset_type: Optional[AssetType] = None,
    job_id: Optional[int] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    query = db.query(Asset).filter(
        Asset.tenant_id == CURRENT_TENANT,
        Asset.parent_asset_id == None,
    )
    if asset_type:
        query = query.filter(Asset.asset_type == asset_type)
    if job_id:
        query = query.filter(Asset.job_id == job_id)
    if q:
        query = query.filter(Asset.original_name.ilike(f"%{q}%"))
    if tag:
        query = query.join(AssetTag).join(Tag).filter(Tag.name == tag)
    assets = query.order_by(Asset.created_at.desc()).all()
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
            "version": a.version,
            "created_at": a.created_at.isoformat(),
        }
        for a in assets
    ]


@router.post("/api/assets/upload", dependencies=[RequireEditDam])
async def upload_asset(
    file: UploadFile = File(...),
    job_id: Optional[int] = Form(None),
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

    asset = Asset(
        filename=filename,
        original_name=file.filename,
        file_path=file_path,
        thumbnail_path=thumbnail_path,
        asset_type=asset_type,
        mime_type=mime_type,
        file_size=len(file_bytes),
        job_id=job_id,
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

    db.commit()
    db.refresh(asset)
    return {"id": asset.id, "filename": asset.filename, "asset_type": asset.asset_type}


@router.get("/download/{asset_id}")
async def download_asset(asset_id: int, db: Session = Depends(get_db)):
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT).first()
    if not a or not os.path.exists(a.file_path):
        raise HTTPException(404, "Asset non trovato")
    return FileResponse(a.file_path, filename=a.original_name, media_type=a.mime_type)


@router.get("/thumbnail/{asset_id}")
async def get_thumbnail(asset_id: int, db: Session = Depends(get_db)):
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT).first()
    if not a or not a.thumbnail_path or not os.path.exists(a.thumbnail_path):
        raise HTTPException(404, "Thumbnail non disponibile")
    return FileResponse(a.thumbnail_path, media_type="image/jpeg")


@router.delete("/api/assets/{asset_id}", dependencies=[RequireEditDam])
async def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    # v3.5.0-alpha.66.15.2 — tenant scope (R1)
    a = db.query(Asset).filter(Asset.id == asset_id, Asset.tenant_id == CURRENT_TENANT).first()
    if not a:
        raise HTTPException(404, "Asset non trovato")
    delete_asset_files(a.file_path, a.thumbnail_path)
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── Tag API ───────────────────────────────────────────────────────────

@router.get("/api/tags")
async def list_tags(db: Session = Depends(get_db)):
    return db.query(Tag).all()
