"""Router admin export/import dati (v3.5.0-alpha.34).

Solo admin (RBAC `is_admin`). Espone:
- GET  /settings/admin/data/export       — restituisce ZIP con tutto + opt-in
- POST /settings/admin/data/import       — riceve ZIP, fa restore
- GET  /settings/admin/data/excel/listino       — solo Excel listino
- GET  /settings/admin/data/excel/quotazioni    — solo Excel quotazioni
"""
from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.rbac import current_user_optional, is_admin
from app.services.data_export import (
    build_export_zip, _build_listino_xlsx, _build_quotazioni_xlsx,
)
from app.services.data_import import restore_from_zip


router = APIRouter(prefix="/settings/admin/data", tags=["admin-data"])


def _require_admin(request: Request):
    user = current_user_optional(request)
    if not is_admin(user):
        raise HTTPException(403, "Solo admin può accedere a questa funzione.")
    return user


def _app_version() -> str:
    try:
        from app.main import app as _app
        return _app.version
    except Exception:
        return "?"


@router.get("/export")
async def export_all(
    request: Request,
    include_env: bool = False,
    include_uploads: bool = False,
    include_trash: bool = False,
    include_memory: bool = True,
    password: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Genera l'archivio ZIP completo. Tutti i flag sono query params così
    l'utente può anche richiamare l'URL con i parametri (es. cron backup
    via wget). Per il form UI usiamo gli stessi parametri."""
    _require_admin(request)
    pwd = (password or "").strip() or None
    data, fname = build_export_zip(
        db,
        include_env=include_env,
        include_uploads=include_uploads,
        include_trash=include_trash,
        include_memory=include_memory,
        password=pwd,
        app_version=_app_version(),
    )
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/excel/listino")
async def export_listino(request: Request, db: Session = Depends(get_db)):
    """Solo Excel listino (no DB, no zip)."""
    _require_admin(request)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _build_listino_xlsx(db, tmp_path)
        data = tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
    from datetime import datetime
    fname = f"mediaflow-listino-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/excel/quotazioni")
async def export_quotazioni(request: Request, db: Session = Depends(get_db)):
    """Solo Excel quotazioni."""
    _require_admin(request)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _build_quotazioni_xlsx(db, tmp_path)
        data = tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass
    from datetime import datetime
    fname = f"mediaflow-quotazioni-{datetime.now():%Y%m%d-%H%M%S}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.post("/import")
async def import_zip(
    request: Request,
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
    restore_env: bool = Form(False),
    restore_uploads: bool = Form(False),
    restore_memory: bool = Form(True),
):
    """Restore da ZIP. ATTENZIONE: sostituisce il DB corrente. Backup auto."""
    _require_admin(request)
    if not file or not file.filename:
        raise HTTPException(400, "File mancante")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "File vuoto")
    pwd = (password or "").strip() or None
    try:
        summary = restore_from_zip(
            payload,
            password=pwd,
            restore_env=restore_env,
            restore_uploads=restore_uploads,
            restore_memory=restore_memory,
            current_app_version=_app_version(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return JSONResponse(summary)
