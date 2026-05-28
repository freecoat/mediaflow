"""
v3.5.0-alpha.172.98 (Bundle L Stack 2) — QC router.

Endpoint REST per il workflow QC event-sourced. Tutti gli endpoint:
- tenant-scoped via current_tenant_id()
- RBAC: write richiede edit_planning_all OR assign_resources
- read richiede view_finance (o assign_resources per planning UI)
- ritornano JSON: l'event ID + il QCReport aggiornato per refresh UI live

Endpoint:
- POST /qc/api/deliverables/{id}/start            → start_qc + snapshot
- POST /qc/api/deliverables/{id}/log-event        → log_error (channel form)
- POST /qc/api/deliverables/{id}/recommendation   → add_recommendation
- POST /qc/api/deliverables/{id}/note             → add_note
- POST /qc/api/deliverables/{id}/correction       → request_correction
- POST /qc/api/deliverables/{id}/signoff          → signoff
- POST /qc/api/deliverables/{id}/pass             → pass_qc
- POST /qc/api/deliverables/{id}/fail             → fail_qc (cascade Bundle I)
- POST /qc/api/deliverables/{id}/conditional      → conditional_qc
- POST /qc/api/deliverables/{id}/reopen           → reopen_qc
- POST /qc/api/deliverables/{id}/rebuild-report   → rebuild_qc_report
- GET  /qc/api/deliverables/{id}/events           → list event stream
- GET  /qc/api/deliverables/{id}/report           → get QCReport
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from app.context import current_tenant_id
from app.database import get_db
from app.models import (
    JobDeliverable, QCEvent, QCReport,
)
from app.services import qc_events
from app.services.delivery_timeline_service import qc_expected_for_deliverable

router = APIRouter(prefix="/qc", tags=["qc"])


# ── Helpers ────────────────────────────────────────────────────────────────

def _fetch_deliverable(db: Session, deliverable_id: int) -> JobDeliverable:
    d = db.query(JobDeliverable).filter(
        JobDeliverable.id == deliverable_id,
        JobDeliverable.tenant_id == current_tenant_id(),
    ).first()
    if not d:
        raise HTTPException(404, "Deliverable non trovato")
    return d


def _serialize_event(ev: QCEvent) -> dict:
    return {
        "id": ev.id,
        "deliverable_id": ev.deliverable_id,
        "asset_id": ev.asset_id,
        "qc_number": ev.qc_number,
        "sequence": ev.sequence,
        "event_type": ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type),
        "payload": ev.payload_json or {},
        "operator_id": ev.operator_id,
        "occurred_at": ev.occurred_at.isoformat() if ev.occurred_at else None,
        "source": ev.source,
    }


def _serialize_report(rep: Optional[QCReport]) -> Optional[dict]:
    if rep is None:
        return None
    return {
        "deliverable_id": rep.deliverable_id,
        "last_qc_number": rep.last_qc_number,
        "overall_status": rep.overall_status,
        "video_errors_count": rep.video_errors_count,
        "audio_errors_count": rep.audio_errors_count,
        "text_errors_count": rep.text_errors_count,
        "recommendations_count": rep.recommendations_count,
        "notes_count": rep.notes_count,
        "open_corrections_count": rep.open_corrections_count,
        "signoffs_count": rep.signoffs_count,
        "max_grade": rep.max_grade,
        "last_operator_id": rep.last_operator_id,
        "last_event_at": rep.last_event_at.isoformat() if rep.last_event_at else None,
        "last_event_id": rep.last_event_id,
        "summary": rep.summary_json,
    }


def _check_write(request: Request) -> Optional[int]:
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not (has_permission(user, "edit_planning_all") or has_permission(user, "assign_resources")):
        raise HTTPException(403, "Permesso insufficiente (richiesto edit_planning_all o assign_resources)")
    return user.id if user else None


def _check_read(request: Request) -> Optional[int]:
    from app.services.rbac import current_user_optional, has_permission
    user = current_user_optional(request)
    if not (
        has_permission(user, "view_finance")
        or has_permission(user, "assign_resources")
        or has_permission(user, "edit_planning_all")
    ):
        raise HTTPException(403, "Permesso insufficiente")
    return user.id if user else None


def _post_response(db: Session, deliverable_id: int, event) -> dict:
    """Output standard write endpoint: event + report aggiornato + delivearble status."""
    db.commit()
    db.refresh(event)
    rep = db.query(QCReport).filter(QCReport.deliverable_id == deliverable_id).first()
    d = db.query(JobDeliverable).filter(JobDeliverable.id == deliverable_id).first()
    return {
        "event": _serialize_event(event),
        "report": _serialize_report(rep),
        "deliverable_status": d.status.value if d and d.status else None,
        "deliverable_qc_substatus": d.qc_substatus.value if d and d.qc_substatus else None,
        "qc_expected": qc_expected_for_deliverable(db, d) if d else None,
    }


# ── Write endpoints ────────────────────────────────────────────────────────

@router.post("/api/deliverables/{deliverable_id}/start")
async def qc_start(
    deliverable_id: int,
    request: Request,
    asset_id: Optional[int] = Form(None),
    refresh_snapshot: bool = Form(True),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    started, _snap = qc_events.start_qc(
        db, deliverable_id,
        asset_id=asset_id, operator_id=uid,
        refresh_snapshot=refresh_snapshot,
    )
    return _post_response(db, deliverable_id, started)


@router.post("/api/deliverables/{deliverable_id}/log-event")
async def qc_log_event(
    deliverable_id: int,
    request: Request,
    channel: str = Form(...),  # "video" | "audio" | "text"
    timecode: Optional[str] = Form(None),
    grade: int = Form(1),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    try:
        ev = qc_events.log_error(
            db, deliverable_id,
            channel=channel, timecode=timecode,
            grade=grade, description=description,
            operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/recommendation")
async def qc_recommendation(
    deliverable_id: int,
    request: Request,
    description: str = Form(...),
    applies_to: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    try:
        ev = qc_events.add_recommendation(
            db, deliverable_id, description,
            applies_to=applies_to, operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/note")
async def qc_note(
    deliverable_id: int,
    request: Request,
    text: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    ev = qc_events.add_note(db, deliverable_id, text, operator_id=uid)
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/correction")
async def qc_correction(
    deliverable_id: int,
    request: Request,
    target_event_ids: str = Form("", description="CSV di event ids es. '12,15,18'"),
    description: str = Form(...),
    due_date: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    ids: list[int] = []
    if target_event_ids:
        for part in target_event_ids.split(","):
            p = part.strip()
            if p.isdigit():
                ids.append(int(p))
    try:
        ev = qc_events.request_correction(
            db, deliverable_id,
            target_event_ids=ids, description=description,
            due_date=due_date, operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/signoff")
async def qc_signoff(
    deliverable_id: int,
    request: Request,
    signer_id: int = Form(...),
    role: str = Form("qc_lead"),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    try:
        ev = qc_events.signoff(
            db, deliverable_id, signer_id=signer_id, role=role,
            note=note, operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/pass")
async def qc_pass(
    deliverable_id: int,
    request: Request,
    overall_grade: Optional[int] = Form(None),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    try:
        ev = qc_events.pass_qc(
            db, deliverable_id,
            overall_grade=overall_grade, note=note, operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/fail")
async def qc_fail(
    deliverable_id: int,
    request: Request,
    primary_cause: str = Form(...),
    max_grade: Optional[int] = Form(None),
    trigger_cascade: bool = Form(True),
    db: Session = Depends(get_db),
):
    """qc_failed -> listener sync qc_substatus=rejected. Se trigger_cascade=True,
    chiama anche qc_cascade.cascade_qc_reject (Bundle I) per cascade asset
    rejected + spawn placeholder + notifica."""
    uid = _check_write(request)
    d = _fetch_deliverable(db, deliverable_id)
    try:
        ev = qc_events.fail_qc(
            db, deliverable_id,
            primary_cause=primary_cause, max_grade=max_grade,
            operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    if trigger_cascade:
        try:
            from app.services.qc_cascade import cascade_qc_reject
            cascade_qc_reject(
                db, d, actor_user_id=uid, reason=primary_cause,
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"[qc_router] cascade_qc_reject failed for #{deliverable_id}: {e}"
            )
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/conditional")
async def qc_conditional(
    deliverable_id: int,
    request: Request,
    conditions: str = Form("", description="CSV oppure JSON array di conditions"),
    pass_when: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    # Parse conditions: prova JSON array, fallback split CSV
    cond_list: list[str] = []
    if conditions:
        import json
        try:
            parsed = json.loads(conditions)
            if isinstance(parsed, list):
                cond_list = [str(x) for x in parsed]
        except (ValueError, TypeError):
            cond_list = [c.strip() for c in conditions.split(",") if c.strip()]
    try:
        ev = qc_events.conditional_qc(
            db, deliverable_id,
            conditions=cond_list, pass_when=pass_when, operator_id=uid,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/reopen")
async def qc_reopen(
    deliverable_id: int,
    request: Request,
    reason: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    try:
        ev = qc_events.reopen_qc(db, deliverable_id, reason=reason, operator_id=uid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _post_response(db, deliverable_id, ev)


@router.post("/api/deliverables/{deliverable_id}/rebuild-report")
async def qc_rebuild_report(
    deliverable_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Forza re-derivazione QCReport leggendo lo stream QCEvent. Utile dopo
    backfill bulk o per riparare drift della projection."""
    _check_write(request)
    _fetch_deliverable(db, deliverable_id)
    rep = qc_events.rebuild_qc_report(db, deliverable_id)
    db.commit()
    return {
        "ok": True,
        "deliverable_id": deliverable_id,
        "report": _serialize_report(rep),
    }


# ── Read endpoints ─────────────────────────────────────────────────────────

@router.get("/api/deliverables/{deliverable_id}/events")
async def qc_list_events(
    deliverable_id: int,
    request: Request,
    qc_number: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Stream eventi QC per il deliverable. Filtro opzionale per qc_number
    (es. solo round 2)."""
    _check_read(request)
    _fetch_deliverable(db, deliverable_id)
    q = db.query(QCEvent).filter(QCEvent.deliverable_id == deliverable_id)
    if qc_number is not None:
        q = q.filter(QCEvent.qc_number == qc_number)
    events = q.order_by(QCEvent.qc_number, QCEvent.sequence, QCEvent.id).all()
    return {
        "deliverable_id": deliverable_id,
        "count": len(events),
        "events": [_serialize_event(ev) for ev in events],
    }


@router.get("/api/deliverables/{deliverable_id}/report")
async def qc_get_report(
    deliverable_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _check_read(request)
    d = _fetch_deliverable(db, deliverable_id)
    rep = db.query(QCReport).filter(QCReport.deliverable_id == deliverable_id).first()
    return {
        "report": _serialize_report(rep),
        "qc_expected": qc_expected_for_deliverable(db, d),
    }
