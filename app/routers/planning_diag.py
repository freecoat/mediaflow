"""Router diagnostica planning — endpoint per ispezione + cleanup booking sporchi.

v3.5.0-alpha.66.20 — Estratto da planning.py (sprint R7.x audit pattern G
"file giganti", planning.py era 4296 righe). Endpoint `/planning/api/diag/*`
spostati qui senza alterare paths esterni:
  - GET  /planning/api/diag/booking-raw/{booking_id}
  - GET  /planning/api/diag/scan-duplicate-overlaps
  - POST /planning/api/diag/cleanup-all-duplicate-overlaps

Tutti gli endpoint richiedono ruolo elevato (manager/admin). Le helper
`_recalc_booking_envelope` e `_log_change` restano in planning.py (riusate
da molti call site) e vengono importate da qui.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Booking, BookingAssignment, BookingChange, BookingStatus
from app.services.rbac import is_elevated, current_user_optional
from app.context import current_tenant_id

router = APIRouter(prefix="/planning/api/diag", tags=["planning-diag"])



def _detect_dup_overlap_pairs(assigns: list) -> list:
    """Per diagnostica: ritorna le coppie (i, j) di assignment con stessa
    risorsa e orari sovrapposti. Vuoto se ok."""
    out = []
    for i in range(len(assigns)):
        for j in range(i + 1, len(assigns)):
            ai, aj = assigns[i], assigns[j]
            if ai.resource_id != aj.resource_id:
                continue
            if ai.start_datetime < aj.end_datetime and aj.start_datetime < ai.end_datetime:
                out.append({
                    "i": i, "j": j,
                    "ass_id_i": ai.id, "ass_id_j": aj.id,
                    "resource_id": ai.resource_id,
                    "i_range": f"{ai.start_datetime.isoformat()} → {ai.end_datetime.isoformat()}",
                    "j_range": f"{aj.start_datetime.isoformat()} → {aj.end_datetime.isoformat()}",
                })
    return out


@router.get("/booking-raw/{booking_id}")
async def diag_booking_raw(booking_id: int, request: Request, db: Session = Depends(get_db)):
    """Dump grezzo di un Booking + i suoi assignments + audit changes recenti.
    Solo manager/admin. Ignora qualunque filtro di status (cancelled compresi)."""
    user = current_user_optional(request)
    if not user or not is_elevated(user):
        raise HTTPException(403, "Solo manager/admin")
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(404, f"Booking #{booking_id} non trovato")
    assigns = db.query(BookingAssignment).filter(
        BookingAssignment.booking_id == booking_id
    ).order_by(BookingAssignment.id).all()
    changes = db.query(BookingChange).filter(
        BookingChange.booking_id == booking_id
    ).order_by(BookingChange.created_at.asc()).all()
    return {
        "booking": {
            "id": b.id, "tenant_id": b.tenant_id,
            "job_id": b.job_id, "job_cost_line_id": b.job_cost_line_id,
            "kind": str(b.kind), "status": str(b.status),
            "execution_status": str(b.execution_status),
            "overtime_status": str(b.overtime_status),
            "start_datetime": b.start_datetime.isoformat() if b.start_datetime else None,
            "end_datetime": b.end_datetime.isoformat() if b.end_datetime else None,
            "notes": b.notes,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        },
        "assignments_count": len(assigns),
        "assignments": [
            {
                "id": a.id, "resource_id": a.resource_id,
                "start_datetime": a.start_datetime.isoformat(),
                "end_datetime": a.end_datetime.isoformat(),
            } for a in assigns
        ],
        "duplicate_overlap_detected": _detect_dup_overlap_pairs(assigns),
        "audit_changes_count": len(changes),
        "audit_changes": [
            {
                "kind": c.kind, "summary": c.summary,
                "user_id": c.user_id, "payload": c.payload,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            } for c in changes
        ],
    }


@router.get("/scan-duplicate-overlaps")
async def diag_scan_duplicate_overlaps(request: Request, db: Session = Depends(get_db)):
    """Scansiona TUTTI i booking del tenant e ritorna quelli che hanno
    almeno una coppia di assignment duplicati con orari sovrapposti.

    Read-only. Solo manager/admin."""
    user = current_user_optional(request)
    if not user or not is_elevated(user):
        raise HTTPException(403, "Solo manager/admin")
    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.assignments), joinedload(Booking.job))
        .filter(
            Booking.tenant_id == current_tenant_id(),
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )
    dirty = []
    total_phantom_hours = 0.0
    for b in bookings:
        pairs = _detect_dup_overlap_pairs(list(b.assignments))
        if not pairs:
            continue
        phantom_h = 0.0
        for p in pairs:
            ai = next((a for a in b.assignments if a.id == p["ass_id_i"]), None)
            aj = next((a for a in b.assignments if a.id == p["ass_id_j"]), None)
            if ai and aj:
                ovs = max(ai.start_datetime, aj.start_datetime)
                ove = min(ai.end_datetime, aj.end_datetime)
                if ove > ovs:
                    phantom_h += (ove - ovs).total_seconds() / 3600.0
        total_phantom_hours += phantom_h
        dirty.append({
            "booking_id": b.id,
            "job_id": b.job_id,
            "job_code": (b.job.code if b.job else None),
            "job_title": (b.job.title if b.job else None),
            "assignments_count": len(b.assignments),
            "duplicate_pairs": pairs,
            "phantom_hours": round(phantom_h, 2),
        })
    return {
        "scanned_bookings": len(bookings),
        "dirty_bookings_count": len(dirty),
        "total_phantom_hours": round(total_phantom_hours, 2),
        "dirty_bookings": dirty,
    }


@router.post("/cleanup-all-duplicate-overlaps")
async def diag_cleanup_all_duplicate_overlaps(
    request: Request,
    dry_run: bool = Form(True),
    db: Session = Depends(get_db),
):
    """Cleanup massivo dei booking con assignment duplicati overlap.

    `dry_run=True` (default): conta cosa cancellerebbe senza toccare nulla.
    `dry_run=False`: esegue. Per ogni booking sporco mantiene il primo
    assignment per orario (e ID più basso a parità di start), cancella gli
    altri della stessa risorsa con overlap. Reconcile cost line per i
    job toccati.

    Solo manager/admin. Operazione irreversibile (in execute mode)."""
    user = current_user_optional(request)
    if not user or not is_elevated(user):
        raise HTTPException(403, "Solo manager/admin")
    # Import locale per evitare circolari (planning.py importa molto).
    from app.routers.planning import _recalc_booking_envelope, _log_change

    bookings = (
        db.query(Booking)
        .options(joinedload(Booking.assignments))
        .filter(
            Booking.tenant_id == current_tenant_id(),
            Booking.status != BookingStatus.cancelled,
        )
        .all()
    )
    actions = []
    total_removed = 0
    affected_jobs = set()
    for b in bookings:
        pairs = _detect_dup_overlap_pairs(list(b.assignments))
        if not pairs:
            continue
        by_res: dict = {}
        for a in b.assignments:
            by_res.setdefault(a.resource_id, []).append(a)
        kept_ids = []
        removed_ids = []
        for rid, lst in by_res.items():
            if len(lst) < 2:
                kept_ids.extend([a.id for a in lst])
                continue
            lst_sorted = sorted(lst, key=lambda x: (x.start_datetime, x.id))
            kept_for_res = [lst_sorted[0]]
            for cand in lst_sorted[1:]:
                conflict = any(
                    cand.start_datetime < k.end_datetime and k.start_datetime < cand.end_datetime
                    for k in kept_for_res
                )
                if conflict:
                    removed_ids.append(cand.id)
                else:
                    kept_for_res.append(cand)
            kept_ids.extend([a.id for a in kept_for_res])
        if not removed_ids:
            continue
        actions.append({
            "booking_id": b.id,
            "job_id": b.job_id,
            "kept_assignment_ids": kept_ids,
            "removed_assignment_ids": removed_ids,
            "removed_count": len(removed_ids),
        })
        total_removed += len(removed_ids)
        if b.job_id:
            affected_jobs.add(b.job_id)
        if not dry_run:
            for aid in removed_ids:
                a = db.query(BookingAssignment).filter(BookingAssignment.id == aid).first()
                if a:
                    db.delete(a)
            _recalc_booking_envelope(b)
            _log_change(db, b.id, "cleanup", f"Cleanup duplicate-overlap: rimossi {len(removed_ids)} assignments",
                        {"removed_ids": removed_ids, "kept_ids": kept_ids})
    if not dry_run and affected_jobs:
        db.flush()
        try:
            from app.services.cost_line_sync import recompute_for_job
            for jid in affected_jobs:
                recompute_for_job(db, jid)
        except Exception as e:
            print(f"[cleanup-all] reconcile fail: {e}")
        db.commit()
    return {
        "dry_run": dry_run,
        "scanned_bookings": len(bookings),
        "dirty_bookings_affected": len(actions),
        "total_assignments_removed": total_removed,
        "affected_jobs": sorted(affected_jobs),
        "actions": actions,
    }
