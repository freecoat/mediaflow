"""Form pubblico richiesta KDM/DKDM (no auth, token capability).
Pattern public-token come tech-sheet/portale."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import KdmRequestLink, KdmRequest

router = APIRouter(prefix="/public/kdm", tags=["kdm-public"])


def _tpl():
    from app.main import templates
    return templates


def _resolve_link(token: str, db: Session) -> KdmRequestLink:
    lnk = (db.query(KdmRequestLink)
           .filter(KdmRequestLink.token == token,
                   KdmRequestLink.is_active == True)  # noqa: E712
           .first())
    if not lnk:
        raise HTTPException(404, "Link non valido o revocato")
    return lnk


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _project_title(link, db) -> str | None:
    """Resolve project title from link, if any."""
    if not link.project_id:
        return None
    from app.models import Project
    p = db.get(Project, link.project_id)
    return getattr(p, "title", None) if p else None


def _notify_finishing(db, req):
    """Notifica in-app (manage_kdm) + email best-effort. Vedi Task 19."""
    from app.services.kdm_notify import notify_new_kdm_request
    notify_new_kdm_request(db, req)


@router.get("/{token}", response_class=HTMLResponse)
async def public_form(token: str, request: Request, db: Session = Depends(get_db)):
    link = _resolve_link(token, db)
    project_title = _project_title(link, db)
    return _tpl().TemplateResponse("pages/kdm_public_form.html", {
        "request": request, "token": token, "pf": link.prefill_json or {},
        "project_title": project_title, "submitted": False})


@router.post("/{token}")
async def public_submit(
        token: str, request: Request, db: Session = Depends(get_db),
        request_type: str = Form("kdm"),
        requested_title: Optional[str] = Form(None),
        requested_cpl_uuid: Optional[str] = Form(None),
        valid_from: Optional[str] = Form(None),
        valid_to: Optional[str] = Form(None),
        cinema_contact_name: Optional[str] = Form(None),
        cinema_contact_email: Optional[str] = Form(None),
        lab_contact_email: Optional[str] = Form(None),
        production_contact_name: Optional[str] = Form(None),
        production_contact_email: Optional[str] = Form(None),
        notes: Optional[str] = Form(None),
        cert_file: Optional[UploadFile] = File(None)):
    link = _resolve_link(token, db)
    # I2: normalize request_type to valid enum values
    if request_type not in ("kdm", "dkdm"):
        request_type = "kdm"
    cert_pem = None
    if cert_file is not None:
        try:
            raw = await cert_file.read()
            if raw:
                cert_pem = raw.decode("utf-8", "ignore")
        except Exception:
            cert_pem = None
    req = KdmRequest(
        tenant_id=link.tenant_id,
        request_type=request_type,
        project_id=link.project_id,
        requested_title=requested_title,
        requested_cpl_uuid=requested_cpl_uuid,
        valid_from=_parse_dt(valid_from),
        valid_to=_parse_dt(valid_to),
        cinema_contact_name=cinema_contact_name,
        cinema_contact_email=cinema_contact_email,
        lab_contact_email=lab_contact_email,
        production_contact_name=production_contact_name,
        production_contact_email=production_contact_email,
        client_cert_pem=cert_pem,
        notes=notes,
        status="received",
        source_link_id=link.id,
        requested_by=cinema_contact_email or production_contact_email)
    db.add(req)
    db.flush()
    # auto-match CPL
    try:
        from app.services.kdm_match import match_request, AUTO_LINK_THRESHOLD
        cands = match_request(db, req)
        if cands and cands[0].get("confidence", 0) >= AUTO_LINK_THRESHOLD:
            req.dcp_cpl_id = cands[0]["dcp_cpl_id"]
            req.matched_confidence = cands[0]["confidence"]
            req.match_source = cands[0]["source"]
            req.status = "matched"
    except Exception:
        pass  # auto-match best-effort; non blocca il salvataggio
    db.commit()
    db.refresh(req)
    _notify_finishing(db, req)
    # I1: resolve project title for success banner (DRY via helper)
    return _tpl().TemplateResponse("pages/kdm_public_form.html", {
        "request": request, "token": token, "pf": {},
        "project_title": _project_title(link, db), "submitted": True})
