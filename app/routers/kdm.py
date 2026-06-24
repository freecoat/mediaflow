"""Router richieste KDM/DKDM (v3.5.0-alpha.172.226). Tracking-only.
Vedi docs/superpowers/specs/2026-06-19-kdm-dkdm-request-design.md
"""
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.context import current_tenant_id
from app.models import KdmRequest, DcpCpl, CinemaFacility, CinemaServer
from app.models import Job, JobDeliverable
from app.models import KdmRequestLink, KdmRequestEvent, KdmRequestCertificate
from app.services.rbac import has_permission, current_user_optional
from app.services.kdm_match import match_request, AUTO_LINK_THRESHOLD
from app.services.kdm_state import transition as _fsm_transition

router = APIRouter(prefix="/kdm", tags=["kdm"])


def _tpl():
    from app.main import templates
    return templates


def _require_kdm(request: Request, db: Session):
    user = current_user_optional(request)
    if not has_permission(user, "manage_kdm"):
        raise HTTPException(status_code=403, detail="Permesso manage_kdm richiesto")
    return user


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def kdm_page(request: Request, db: Session = Depends(get_db)):
    return _tpl().TemplateResponse("pages/kdm.html", {"request": request})


@router.get("/api/requests")
async def list_requests(
    request: Request,
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    type: Optional[str] = None,
):
    _require_kdm(request, db)
    q = (
        db.query(KdmRequest)
        .filter(
            KdmRequest.tenant_id == current_tenant_id(),
            KdmRequest.deleted_at.is_(None),
        )
    )
    if status:
        q = q.filter(KdmRequest.status == status)
    if type:
        q = q.filter(KdmRequest.request_type == type)
    rows = q.order_by(KdmRequest.requested_at.desc()).all()
    return JSONResponse([
        {
            "id": r.id,
            "request_type": r.request_type,
            "status": r.status,
            "client_id": r.client_id,
            "project_id": r.project_id,
            "requested_title": r.requested_title,
            "valid_from": r.valid_from.isoformat() if r.valid_from else None,
            "valid_to": r.valid_to.isoformat() if r.valid_to else None,
            "matched_confidence": r.matched_confidence,
            "dcp_cpl_id": r.dcp_cpl_id,
            "job_deliverable_id": r.job_deliverable_id,
        }
        for r in rows
    ])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _serialize(r: KdmRequest) -> dict:
    return {
        "id": r.id,
        "request_type": r.request_type,
        "status": r.status,
        "client_id": r.client_id,
        "project_id": r.project_id,
        "dcp_cpl_id": r.dcp_cpl_id,
        "job_deliverable_id": r.job_deliverable_id,
        "matched_confidence": r.matched_confidence,
        "match_source": r.match_source,
        "requested_title": r.requested_title,
        "requested_cpl_uuid": r.requested_cpl_uuid,
    }


def _cert_json(c: KdmRequestCertificate) -> dict:
    return {
        "id": c.id,
        "kind": c.kind,
        "label": c.label,
        "serial": c.serial,
        "cert_thumbprint": c.cert_thumbprint,
        "cert_expires_at": c.cert_expires_at.isoformat() if c.cert_expires_at else None,
        "has_pem": bool(c.cert_pem),
    }


def _has_credentials(r: KdmRequest, certs) -> bool:
    """≥1 credenziale presente: riga cert/serial OPPURE legacy client_cert_pem."""
    return bool(certs) or bool(r.client_cert_pem)


def _serialize_detail(db, r: KdmRequest) -> dict:
    """Vista completa human-readable per il pannello dettaglio."""
    fac = db.get(CinemaFacility, r.target_facility_id) if r.target_facility_id else None
    srv = db.get(CinemaServer, r.target_server_id) if r.target_server_id else None
    cpl = db.get(DcpCpl, r.dcp_cpl_id) if r.dcp_cpl_id else None
    events = (
        db.query(KdmRequestEvent)
        .filter(KdmRequestEvent.kdm_request_id == r.id)
        .order_by(KdmRequestEvent.created_at.asc())
        .all()
    )
    certs = (
        db.query(KdmRequestCertificate)
        .filter(KdmRequestCertificate.kdm_request_id == r.id)
        .order_by(KdmRequestCertificate.created_at.asc())
        .all()
    )
    return {
        "id": r.id,
        "request_type": r.request_type,
        "status": r.status,
        "client_id": r.client_id,
        "project_id": r.project_id,
        "dcp_cpl_id": r.dcp_cpl_id,
        "dcp_cpl_title": getattr(cpl, "content_title_text", None) if cpl else None,
        "job_deliverable_id": r.job_deliverable_id,
        "job_deliverable_produced_id": r.job_deliverable_produced_id,
        "matched_confidence": r.matched_confidence,
        "match_source": r.match_source,
        "requested_title": r.requested_title,
        "requested_cpl_uuid": r.requested_cpl_uuid,
        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "delivery_method": r.delivery_method,
        "target_facility_id": r.target_facility_id,
        "target_facility_name": getattr(fac, "name", None) if fac else None,
        "target_server_id": r.target_server_id,
        "target_server_serial": getattr(srv, "serial", None) if srv else None,
        "requested_by": r.requested_by,
        "notes": r.notes,
        "cinema_contact_name": r.cinema_contact_name,
        "cinema_contact_email": r.cinema_contact_email,
        "lab_contact_email": r.lab_contact_email,
        "production_contact_name": r.production_contact_name,
        "production_contact_email": r.production_contact_email,
        "has_client_cert": bool(r.client_cert_pem),
        "certificates": [_cert_json(c) for c in certs],
        "has_credentials": _has_credentials(r, certs),
        "source_link_id": r.source_link_id,
        "requested_at": r.requested_at.isoformat() if r.requested_at else None,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
        "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        "events": [
            {
                "event_type": e.event_type,
                "payload": e.payload_json,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
    }


# Cammino "felice" per le azioni leggibili Emetti/Conferma. Ogni hop è
# validato da kdm_state.ALLOWED_TRANSITIONS; salta gli stati già superati.
_HAPPY_PATH = ["received", "matched", "keys_pending", "generated", "delivered", "confirmed"]


def _advance_to(db, r: KdmRequest, target: str, user_id=None):
    """Avanza la richiesta lungo _HAPPY_PATH fino a `target` (incluso).

    Esegue ogni transizione legale intermedia. Solleva ValueError se lo stato
    corrente è terminale/fuori cammino o `target` non è raggiungibile in avanti.
    """
    if target not in _HAPPY_PATH:
        raise ValueError(f"Stato target non valido: {target!r}")
    if r.status not in _HAPPY_PATH:
        raise ValueError(f"Stato corrente {r.status!r} fuori dal cammino di emissione")
    cur_i = _HAPPY_PATH.index(r.status)
    tgt_i = _HAPPY_PATH.index(target)
    if tgt_i <= cur_i:
        raise ValueError(f"Richiesta già in stato {r.status!r}: nessun avanzamento a {target!r}")
    for nxt in _HAPPY_PATH[cur_i + 1 : tgt_i + 1]:
        _fsm_transition(db, r, nxt, user_id=user_id)


def _apply_link(db, r: KdmRequest, cpl_id: int, confidence: int, source: str):
    """Link a CPL to a request; resolve project_id via Job (JobDeliverable has no project_id)."""
    cpl = db.get(DcpCpl, cpl_id)
    if not cpl or cpl.tenant_id != current_tenant_id():
        raise HTTPException(404, "CPL non trovata")
    r.dcp_cpl_id = cpl.id
    r.job_deliverable_id = cpl.job_deliverable_id
    r.matched_confidence = confidence
    r.match_source = source
    if cpl.job_deliverable_id:
        jd = db.get(JobDeliverable, cpl.job_deliverable_id)
        if jd is not None:
            job = db.get(Job, jd.job_id)
            r.project_id = getattr(job, "project_id", None) or r.project_id
    if r.status == "received":
        _fsm_transition(db, r, "matched")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/requests")
async def create_request(
    request: Request,
    db: Session = Depends(get_db),
    request_type: str = Form("kdm"),
    client_id: Optional[int] = Form(None),
    requested_title: Optional[str] = Form(None),
    requested_cpl_uuid: Optional[str] = Form(None),
    target_facility_id: Optional[int] = Form(None),
    target_server_id: Optional[int] = Form(None),
    valid_from: Optional[str] = Form(None),
    valid_to: Optional[str] = Form(None),
    delivery_method: str = Form("email"),
    requested_by: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    _require_kdm(request, db)
    r = KdmRequest(
        tenant_id=current_tenant_id(),
        request_type=request_type,
        client_id=client_id,
        requested_title=requested_title,
        requested_cpl_uuid=requested_cpl_uuid,
        target_facility_id=target_facility_id,
        target_server_id=target_server_id,
        valid_from=_parse_dt(valid_from),
        valid_to=_parse_dt(valid_to),
        delivery_method=delivery_method,
        requested_by=requested_by,
        notes=notes,
        status="received",
    )
    db.add(r)
    db.flush()
    cands = match_request(db, r)
    if cands and cands[0]["confidence"] >= AUTO_LINK_THRESHOLD:
        _apply_link(db, r, cands[0]["dcp_cpl_id"], cands[0]["confidence"], cands[0]["source"])
    db.commit()
    db.refresh(r)
    return _serialize(r)


@router.get("/api/requests/{rid}")
async def get_request(rid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    return _serialize_detail(db, r)


_EDITABLE_FIELDS = (
    "requested_title",
    "requested_cpl_uuid",
    "delivery_method",
    "requested_by",
    "notes",
    "cinema_contact_name",
    "cinema_contact_email",
    "lab_contact_email",
    "production_contact_name",
    "production_contact_email",
)


@router.post("/api/requests/{rid}")
async def update_request(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
    requested_title: Optional[str] = Form(None),
    requested_cpl_uuid: Optional[str] = Form(None),
    delivery_method: Optional[str] = Form(None),
    requested_by: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    valid_from: Optional[str] = Form(None),
    valid_to: Optional[str] = Form(None),
    target_facility_id: Optional[int] = Form(None),
    cinema_contact_name: Optional[str] = Form(None),
    cinema_contact_email: Optional[str] = Form(None),
    lab_contact_email: Optional[str] = Form(None),
    production_contact_name: Optional[str] = Form(None),
    production_contact_email: Optional[str] = Form(None),
):
    """Producer/operatore ampliano e correggono la richiesta.

    Campi testo: valorizzati se forniti; sentinel '0' per svuotare (memo
    feedback_empty_multipart_is_none — FormData vuoto arriva come None).
    Date: ISO se fornite; '0' per azzerare.
    """
    _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")

    local = locals()
    for f in _EDITABLE_FIELDS:
        v = local.get(f)
        if v is None:
            continue
        setattr(r, f, None if v == "0" else v)

    for f, raw in (("valid_from", valid_from), ("valid_to", valid_to)):
        if raw is None:
            continue
        setattr(r, f, None if raw == "0" else _parse_dt(raw))

    if target_facility_id is not None:
        if target_facility_id == 0:
            r.target_facility_id = None
        else:
            fac = db.get(CinemaFacility, target_facility_id)
            if not fac or fac.tenant_id != current_tenant_id():
                raise HTTPException(404, "Facility non trovata")
            r.target_facility_id = target_facility_id

    db.commit()
    db.refresh(r)
    return _serialize_detail(db, r)


@router.post("/api/requests/{rid}/emit")
async def emit_kdm(rid: int, request: Request, db: Session = Depends(get_db)):
    """Registra l'emissione (KDM Studio emette esternamente): porta la
    richiesta a 'generated' e materializza il deliverable. Memo
    project_kdm_redesign: in Claqo la KDM resta solo come registro."""
    user = _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    # Gate Step 2: niente emissione senza ≥1 credenziale (cert o serial).
    certs = (
        db.query(KdmRequestCertificate)
        .filter(KdmRequestCertificate.kdm_request_id == r.id)
        .all()
    )
    if not _has_credentials(r, certs):
        raise HTTPException(
            400, "Serve almeno un certificato o serial number per emettere la KDM"
        )
    try:
        _advance_to(db, r, "generated", user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    db.refresh(r)
    return _serialize_detail(db, r)


@router.post("/api/requests/{rid}/confirm-delivery")
async def confirm_delivery(rid: int, request: Request, db: Session = Depends(get_db)):
    """Conferma avvenuta consegna: porta la richiesta a 'confirmed'."""
    user = _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    try:
        _advance_to(db, r, "confirmed", user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    db.refresh(r)
    return _serialize_detail(db, r)


# ---------------------------------------------------------------------------
# Step 2 — credenziali richiesta: certificati multipli + serial number
# ---------------------------------------------------------------------------

def _get_request_or_404(db, rid: int) -> KdmRequest:
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    return r


@router.get("/api/requests/{rid}/certs")
async def list_certs(rid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    r = _get_request_or_404(db, rid)
    certs = (
        db.query(KdmRequestCertificate)
        .filter(KdmRequestCertificate.kdm_request_id == r.id)
        .order_by(KdmRequestCertificate.created_at.asc())
        .all()
    )
    return [_cert_json(c) for c in certs]


@router.post("/api/requests/{rid}/certs")
async def add_cert(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
    kind: str = Form("cert"),
    cert_pem: Optional[str] = Form(None),
    serial: Optional[str] = Form(None),
    label: Optional[str] = Form(None),
):
    """Aggiunge una credenziale: 'cert' (PEM, thumbprint/scadenza parsati) o 'serial'."""
    _require_kdm(request, db)
    r = _get_request_or_404(db, rid)
    if kind not in ("cert", "serial"):
        raise HTTPException(400, "kind deve essere 'cert' o 'serial'")

    c = KdmRequestCertificate(
        tenant_id=current_tenant_id(),
        kdm_request_id=r.id,
        kind=kind,
        label=label,
    )
    if kind == "cert":
        if not cert_pem or not cert_pem.strip():
            raise HTTPException(400, "cert_pem richiesto per kind='cert'")
        c.cert_pem = cert_pem
        meta = parse_cert(cert_pem)
        c.cert_thumbprint = meta["thumbprint"]
        c.cert_expires_at = meta["expires_at"]
    else:
        if not serial or not serial.strip():
            raise HTTPException(400, "serial richiesto per kind='serial'")
        c.serial = serial.strip()

    db.add(c)
    db.commit()
    db.refresh(c)
    return _cert_json(c)


@router.delete("/api/requests/{rid}/certs/{cid}")
async def delete_cert(rid: int, cid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    r = _get_request_or_404(db, rid)
    c = db.get(KdmRequestCertificate, cid)
    if not c or c.kdm_request_id != r.id or c.tenant_id != current_tenant_id():
        raise HTTPException(404, "Credenziale non trovata")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/api/requests/{rid}/match")
async def rematch(rid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    return {"candidates": match_request(db, r)}


@router.post("/api/requests/{rid}/link")
async def link_cpl(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
    dcp_cpl_id: int = Form(...),
):
    _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    cands_map = {c["dcp_cpl_id"]: c for c in match_request(db, r)}
    c = cands_map.get(dcp_cpl_id, {"confidence": 0, "source": "manual_link"})
    _apply_link(db, r, dcp_cpl_id, c["confidence"], c["source"])
    db.commit()
    db.refresh(r)
    return _serialize(r)


@router.post("/api/requests/{rid}/transition")
async def do_transition(
    rid: int,
    request: Request,
    db: Session = Depends(get_db),
    to_status: str = Form(...),
):
    user = _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    try:
        _fsm_transition(db, r, to_status, user_id=getattr(user, "id", None))
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    db.refresh(r)
    return _serialize(r)


@router.delete("/api/requests/{rid}")
async def soft_delete(rid: int, request: Request, db: Session = Depends(get_db)):
    from app.services.clock import now_utc
    user = _require_kdm(request, db)
    r = db.get(KdmRequest, rid)
    if not r or r.tenant_id != current_tenant_id() or r.deleted_at:
        raise HTTPException(404, "Richiesta non trovata")
    r.deleted_at = now_utc()
    r.deleted_by_user_id = getattr(user, "id", None)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Task 11 — CinemaFacility + CinemaServer CRUD + cert upload
# ---------------------------------------------------------------------------

from app.services.kdm_cert import parse_cert  # noqa: E402


def _fac_json(f: CinemaFacility) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "city": f.city,
        "country": f.country,
        "contact_email": f.contact_email,
        "kind": f.kind,
    }


def _srv_json(s: CinemaServer) -> dict:
    return {
        "id": s.id,
        "facility_id": s.facility_id,
        "manufacturer": s.manufacturer,
        "model": s.model,
        "serial": s.serial,
        "cert_thumbprint": s.cert_thumbprint,
        "cert_expires_at": s.cert_expires_at.isoformat() if s.cert_expires_at else None,
    }


@router.get("/api/facilities")
async def list_facilities(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    rows = (
        db.query(CinemaFacility)
        .filter(
            CinemaFacility.tenant_id == current_tenant_id(),
            CinemaFacility.is_active == True,  # noqa: E712
        )
        .order_by(CinemaFacility.name)
        .all()
    )
    return [_fac_json(f) for f in rows]


@router.post("/api/facilities")
async def create_facility(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    kind: str = Form("cinema"),
    city: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
):
    _require_kdm(request, db)
    f = CinemaFacility(
        tenant_id=current_tenant_id(),
        name=name,
        kind=kind,
        city=city,
        country=country,
        contact_email=contact_email,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return _fac_json(f)


@router.put("/api/facilities/{fid}")
async def update_facility(
    fid: int,
    request: Request,
    db: Session = Depends(get_db),
    name: Optional[str] = Form(None),
    kind: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
):
    _require_kdm(request, db)
    f = db.get(CinemaFacility, fid)
    if not f or f.tenant_id != current_tenant_id():
        raise HTTPException(404, "Facility non trovata")
    for k, v in (
        ("name", name),
        ("kind", kind),
        ("city", city),
        ("country", country),
        ("contact_email", contact_email),
    ):
        if v is not None:
            setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return _fac_json(f)


@router.delete("/api/facilities/{fid}")
async def delete_facility(fid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    f = db.get(CinemaFacility, fid)
    if not f or f.tenant_id != current_tenant_id():
        raise HTTPException(404, "Facility non trovata")
    f.is_active = False
    db.commit()
    return {"ok": True}


@router.get("/api/servers")
async def list_servers(
    request: Request,
    db: Session = Depends(get_db),
    facility_id: Optional[int] = None,
):
    _require_kdm(request, db)
    q = db.query(CinemaServer).filter(
        CinemaServer.tenant_id == current_tenant_id(),
        CinemaServer.is_active == True,  # noqa: E712
    )
    if facility_id:
        q = q.filter(CinemaServer.facility_id == facility_id)
    return [_srv_json(s) for s in q.order_by(CinemaServer.serial).all()]


@router.post("/api/servers")
async def create_server(
    request: Request,
    db: Session = Depends(get_db),
    facility_id: int = Form(...),
    manufacturer: str = Form("other"),
    model: Optional[str] = Form(None),
    serial: Optional[str] = Form(None),
):
    _require_kdm(request, db)
    # Cross-tenant facility validation: facility must belong to current tenant
    fac = db.get(CinemaFacility, facility_id)
    if not fac or fac.tenant_id != current_tenant_id():
        raise HTTPException(404, "Facility non trovata")
    s = CinemaServer(
        tenant_id=current_tenant_id(),
        facility_id=facility_id,
        manufacturer=manufacturer,
        model=model,
        serial=serial,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _srv_json(s)


@router.put("/api/servers/{sid}")
async def update_server(
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    manufacturer: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    serial: Optional[str] = Form(None),
):
    _require_kdm(request, db)
    s = db.get(CinemaServer, sid)
    if not s or s.tenant_id != current_tenant_id():
        raise HTTPException(404, "Server non trovato")
    for k, v in (("manufacturer", manufacturer), ("model", model), ("serial", serial)):
        if v is not None:
            setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _srv_json(s)


@router.delete("/api/servers/{sid}")
async def delete_server(sid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    s = db.get(CinemaServer, sid)
    if not s or s.tenant_id != current_tenant_id():
        raise HTTPException(404, "Server non trovato")
    s.is_active = False
    db.commit()
    return {"ok": True}


@router.post("/api/servers/{sid}/cert")
async def upload_cert(
    sid: int,
    request: Request,
    db: Session = Depends(get_db),
    cert_pem: str = Form(...),
):
    _require_kdm(request, db)
    s = db.get(CinemaServer, sid)
    if not s or s.tenant_id != current_tenant_id():
        raise HTTPException(404, "Server non trovato")
    meta = parse_cert(cert_pem)
    s.cert_pem = cert_pem
    s.cert_thumbprint = meta["thumbprint"]
    s.cert_expires_at = meta["expires_at"]
    db.commit()
    db.refresh(s)
    return _srv_json(s)


# ---------------------------------------------------------------------------
# Task 12 — CPL list / parse / manual / scan endpoints
# ---------------------------------------------------------------------------

def _cpl_json(c: DcpCpl) -> dict:
    return {
        "id": c.id,
        "cpl_uuid": c.cpl_uuid,
        "content_title_text": c.content_title_text,
        "source": c.source,
        "encrypted": c.encrypted,
        "job_deliverable_id": c.job_deliverable_id,
    }


@router.get("/api/cpl")
async def list_cpl(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    rows = (
        db.query(DcpCpl)
        .filter(
            DcpCpl.tenant_id == current_tenant_id(),
            DcpCpl.is_active == True,  # noqa: E712
        )
        .order_by(DcpCpl.content_title_text)
        .all()
    )
    return [_cpl_json(c) for c in rows]


@router.post("/api/cpl/parse")
async def cpl_parse(
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    job_deliverable_id: Optional[int] = Form(None),
):
    _require_kdm(request, db)
    from app.services.cpl_parser import parse_cpl
    data = await file.read()
    try:
        meta = parse_cpl(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    c = DcpCpl(
        tenant_id=current_tenant_id(),
        cpl_uuid=meta["cpl_uuid"],
        content_title_text=meta["content_title_text"],
        edit_rate=meta["edit_rate"],
        duration_frames=meta["duration_frames"],
        encrypted=meta["encrypted"],
        key_ids=meta["key_ids"],
        source="parsed_xml",
        job_deliverable_id=job_deliverable_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _cpl_json(c)


@router.post("/api/cpl/manual")
async def cpl_manual(
    request: Request,
    db: Session = Depends(get_db),
    cpl_uuid: str = Form(...),
    content_title_text: Optional[str] = Form(None),
    job_deliverable_id: Optional[int] = Form(None),
):
    _require_kdm(request, db)
    c = DcpCpl(
        tenant_id=current_tenant_id(),
        cpl_uuid=cpl_uuid,
        content_title_text=content_title_text,
        source="manual",
        job_deliverable_id=job_deliverable_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _cpl_json(c)


@router.post("/api/cpl/scan")
async def cpl_scan(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    # v1: lo scan filesystem via agent è progettato ma non implementato.
    # Riusa l'agent storage esistente in fase 2 (memory: browse storage via agent).
    return JSONResponse(
        status_code=501,
        content={"ok": False, "detail": "Scan agent in fase 2"},
    )


# ---------------------------------------------------------------------------
# Task 17 — public request-link generation (operator side)
# ---------------------------------------------------------------------------

def _public_base(request: Request) -> str:
    """Rispetta proxy/tunnel: usa header host. Mirror del pattern portal.py."""
    return str(request.base_url).rstrip("/")


@router.post("/api/links")
async def create_link(
    request: Request,
    db: Session = Depends(get_db),
    project_id: Optional[int] = Form(None),
    request_type: Optional[str] = Form(None),
    prefill_title: Optional[str] = Form(None),
    prefill_cpl_uuid: Optional[str] = Form(None),
    prefill_notes: Optional[str] = Form(None),
):
    user = _require_kdm(request, db)
    prefill = {k: v for k, v in {
        "request_type": request_type,
        "requested_title": prefill_title,
        "requested_cpl_uuid": prefill_cpl_uuid,
        "notes": prefill_notes,
    }.items() if v}
    link = KdmRequestLink(
        tenant_id=current_tenant_id(),
        token=secrets.token_hex(32),
        project_id=project_id,
        prefill_json=prefill or None,
        created_by_user_id=getattr(user, "id", None),
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return {
        "id": link.id,
        "token": link.token,
        "url": f"{_public_base(request)}/public/kdm/{link.token}",
    }


@router.get("/api/links")
async def list_links(request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    rows = (
        db.query(KdmRequestLink)
        .filter(
            KdmRequestLink.tenant_id == current_tenant_id(),
            KdmRequestLink.is_active == True,  # noqa: E712
        )
        .order_by(KdmRequestLink.created_at.desc())
        .all()
    )
    base = _public_base(request)
    return [
        {
            "id": lnk.id,
            "token": lnk.token,
            "project_id": lnk.project_id,
            "url": f"{base}/public/kdm/{lnk.token}",
        }
        for lnk in rows
    ]


@router.post("/api/links/{lid}/revoke")
async def revoke_link(lid: int, request: Request, db: Session = Depends(get_db)):
    _require_kdm(request, db)
    lnk = db.get(KdmRequestLink, lid)
    if not lnk or lnk.tenant_id != current_tenant_id():
        raise HTTPException(404, "Link non trovato")
    lnk.is_active = False
    db.commit()
    return {"ok": True}
