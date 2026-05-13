"""Router AnomalyEntry / Workflow anomalie fatturazione (v3.5.0-alpha.89 — S4).

Stateful workflow per anomalie: open → handled (con action+target) | dismissed.
Detector idempotente (anomaly_detector.py) popola la tabella; questo router
espone:
- GET /finance/api/anomalies/v2 — lista con filtri (status, type, period)
- POST /finance/api/anomalies/detect — re-scan idempotente
- POST /finance/api/anomalies/{id}/handle — applica azione singola
- POST /finance/api/anomalies/bulk-handle — multiselect
- POST /finance/api/anomalies/{id}/dismiss — chiudi senza azione
- POST /finance/api/anomalies/{id}/reopen — riapri (status → open)

3 azioni operative:
- rimanda_commerciale: solo cambio stato workflow + nota; nessun side-effect DB
- rivaluta_producer: idem (cambio stato + nota)
- write_off_loss: crea LossEntry(amount, reason=written_off, project)
- overhead_cost: crea OverheadCost(category=other, amount_net=...)

Le azioni rimanda/rivaluta non hanno target (è solo audit del workflow);
write-off/overhead creano un record concreto e linkano `handled_target_id`.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import (
    AnomalyAction,
    AnomalyEntry,
    AnomalySourceKind,
    AnomalyStatus,
    AnomalyType,
    Job,
    LossEntry,
    LossReason,
    OverheadCost,
    OverheadCostCategory,
    Project,
)
from app.services.anomaly_detector import detect_all
from app.services.rbac import current_user_optional, requires_permission
from app.context import current_tenant_id

router = APIRouter(prefix="/finance", tags=["anomalies"])

RequireViewAnomalies = Depends(requires_permission("view_anomalies"))
RequireHandleAnomalies = Depends(requires_permission("handle_anomalies"))


def _to_dict(a: AnomalyEntry) -> dict:
    return {
        "id": a.id,
        "anomaly_type": a.anomaly_type.value if a.anomaly_type else None,
        "source_kind": a.source_kind.value if a.source_kind else None,
        "source_id": a.source_id,
        "dedup_key": a.dedup_key,
        "project_id": a.project_id,
        "project_title": a.project.title if a.project else None,
        "project_code": a.project.code if a.project else None,
        "job_id": a.job_id,
        "job_code": a.job.code if a.job else None,
        "client_id": a.client_id,
        "client_name": a.client.name if a.client else None,
        "amount": round(a.amount or 0, 2),
        "description": a.description,
        "detected_at": a.detected_at.isoformat() if a.detected_at else None,
        "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        "status": a.status.value if a.status else None,
        "handled_action": a.handled_action.value if a.handled_action else None,
        "handled_at": a.handled_at.isoformat() if a.handled_at else None,
        "handled_target_kind": a.handled_target_kind,
        "handled_target_id": a.handled_target_id,
        "handled_by_user_id": a.handled_by_user_id,
        "notes": a.notes,
    }


@router.get("/api/anomalies/v2", dependencies=[RequireViewAnomalies])
async def list_anomalies(
    status: Optional[str] = "open",
    anomaly_type: Optional[str] = None,
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Lista anomalie con filtri. Default: solo open."""
    q = (
        db.query(AnomalyEntry)
        .options(
            joinedload(AnomalyEntry.project),
            joinedload(AnomalyEntry.job),
            joinedload(AnomalyEntry.client),
        )
        .filter(AnomalyEntry.tenant_id == current_tenant_id())
    )
    if status and status != "all":
        try:
            q = q.filter(AnomalyEntry.status == AnomalyStatus(status))
        except ValueError:
            raise HTTPException(400, f"status invalido: {status}")
    if anomaly_type:
        try:
            q = q.filter(AnomalyEntry.anomaly_type == AnomalyType(anomaly_type))
        except ValueError:
            raise HTTPException(400, f"anomaly_type invalido: {anomaly_type}")
    if project_id:
        q = q.filter(AnomalyEntry.project_id == project_id)
    if client_id:
        q = q.filter(AnomalyEntry.client_id == client_id)
    if from_date:
        q = q.filter(AnomalyEntry.detected_at >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        q = q.filter(AnomalyEntry.detected_at <= datetime.combine(to_date, datetime.max.time()))
    rows = q.order_by(AnomalyEntry.detected_at.desc()).all()
    return [_to_dict(a) for a in rows]


@router.get("/api/anomalies/v2/summary", dependencies=[RequireViewAnomalies])
async def summary_anomalies(db: Session = Depends(get_db)):
    """KPI per dashboard: conteggi e totale € per tipo, solo open."""
    from sqlalchemy import func
    rows = (
        db.query(
            AnomalyEntry.anomaly_type,
            func.count(AnomalyEntry.id).label("n"),
            func.sum(AnomalyEntry.amount).label("total"),
        )
        .filter(
            AnomalyEntry.tenant_id == current_tenant_id(),
            AnomalyEntry.status == AnomalyStatus.open,
        )
        .group_by(AnomalyEntry.anomaly_type)
        .all()
    )
    out = {t.value: {"n": 0, "total": 0.0} for t in AnomalyType}
    for t, n, tot in rows:
        out[t.value if hasattr(t, "value") else t] = {
            "n": int(n or 0),
            "total": round(float(tot or 0), 2),
        }
    out["_total_open"] = sum(v["n"] for v in out.values() if isinstance(v, dict))
    return out


@router.post("/api/anomalies/detect", dependencies=[RequireHandleAnomalies])
async def detect_anomalies(db: Session = Depends(get_db)):
    """Re-scan idempotente. Upsert per dedup_key. Aggiorna last_seen_at +
    amount per anomalie esistenti, crea nuove per quelle non viste."""
    counts = detect_all(db)
    return {"ok": True, **counts}


def _handle_single(
    db: Session,
    entry: AnomalyEntry,
    action: AnomalyAction,
    user_id: Optional[int],
    notes: Optional[str],
) -> dict:
    """Applica azione su 1 anomalia. Crea LossEntry o OverheadCost se servono."""
    if entry.status != AnomalyStatus.open:
        raise HTTPException(409, f"Anomalia #{entry.id} non è open (status={entry.status.value})")

    target_kind = None
    target_id = None

    if action == AnomalyAction.write_off_loss:
        if not entry.project_id:
            raise HTTPException(400, "write-off richiede project_id (anomalia senza progetto)")
        loss = LossEntry(
            tenant_id=current_tenant_id(),
            project_id=entry.project_id,
            job_cost_line_id=(entry.source_id if entry.source_kind == AnomalySourceKind.jcl else None),
            amount=float(entry.amount or 0),
            reason=LossReason.written_off,
            notes=f"Da anomalia #{entry.id} ({entry.anomaly_type.value}): {entry.description}"
                  + (f"\n\nNote operatore: {notes}" if notes else ""),
            created_by_user_id=user_id,
        )
        db.add(loss)
        db.flush()
        target_kind = "LossEntry"
        target_id = loss.id

    elif action == AnomalyAction.overhead_cost:
        # Genera codice OH auto-incrementale
        year = datetime.utcnow().year
        prefix = f"OH-{year}-"
        last = (
            db.query(OverheadCost)
            .filter(
                OverheadCost.tenant_id == current_tenant_id(),
                OverheadCost.code.like(f"{prefix}%"),
            )
            .order_by(OverheadCost.id.desc())
            .first()
        )
        next_num = 1
        if last and last.code.startswith(prefix):
            try:
                next_num = int(last.code[len(prefix):]) + 1
            except ValueError:
                pass
        code = f"{prefix}{next_num:04d}"
        amount_net = float(entry.amount or 0)
        oc = OverheadCost(
            tenant_id=current_tenant_id(),
            code=code,
            category=OverheadCostCategory.other,
            title=f"Da anomalia: {entry.description[:200]}",
            description=f"Generato da anomalia #{entry.id} ({entry.anomaly_type.value})"
                        + (f"\n\nNote: {notes}" if notes else ""),
            amount_net=amount_net,
            vat_rate=0.0,
            amount_vat=0.0,
            amount_total=amount_net,
            cost_date=date.today(),
            source_project_id=entry.project_id,
            created_by_user_id=user_id,
        )
        db.add(oc)
        db.flush()
        target_kind = "OverheadCost"
        target_id = oc.id

    # rimanda_commerciale / rivaluta_producer: solo cambio stato workflow

    entry.status = AnomalyStatus.handled
    entry.handled_action = action
    entry.handled_at = datetime.utcnow()
    entry.handled_by_user_id = user_id
    entry.handled_target_kind = target_kind
    entry.handled_target_id = target_id
    if notes:
        entry.notes = (entry.notes or "") + f"\n[{datetime.utcnow().isoformat()}] {notes}"

    return {
        "anomaly_id": entry.id,
        "action": action.value,
        "target_kind": target_kind,
        "target_id": target_id,
    }


@router.post("/api/anomalies/{anomaly_id}/handle", dependencies=[RequireHandleAnomalies])
async def handle_anomaly(
    request: Request,
    anomaly_id: int,
    action: str = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Applica azione su singola anomalia."""
    try:
        act = AnomalyAction(action)
    except ValueError:
        raise HTTPException(400, f"action invalido: {action} (atteso: {[a.value for a in AnomalyAction]})")
    entry = (
        db.query(AnomalyEntry)
        .filter(AnomalyEntry.id == anomaly_id, AnomalyEntry.tenant_id == current_tenant_id())
        .first()
    )
    if not entry:
        raise HTTPException(404, "Anomalia non trovata")
    user = current_user_optional(request)
    result = _handle_single(db, entry, act, user.id if user else None, notes)
    db.commit()
    return {"ok": True, **result}


@router.post("/api/anomalies/bulk-handle", dependencies=[RequireHandleAnomalies])
async def bulk_handle_anomalies(
    request: Request,
    anomaly_ids: str = Form(...),  # CSV
    action: str = Form(...),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Applica azione su N anomalie selezionate. All-or-nothing: 1 errore
    rollback tutto."""
    try:
        act = AnomalyAction(action)
    except ValueError:
        raise HTTPException(400, f"action invalido: {action}")
    try:
        ids = [int(x.strip()) for x in anomaly_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(400, "anomaly_ids deve essere CSV di interi")
    if not ids:
        raise HTTPException(400, "Nessun ID fornito")
    if len(ids) > 200:
        raise HTTPException(400, "Massimo 200 anomalie per chiamata bulk")

    user = current_user_optional(request)
    user_id = user.id if user else None
    entries = (
        db.query(AnomalyEntry)
        .filter(AnomalyEntry.id.in_(ids), AnomalyEntry.tenant_id == current_tenant_id())
        .all()
    )
    if len(entries) != len(ids):
        missing = set(ids) - {e.id for e in entries}
        raise HTTPException(404, f"Anomalie non trovate: {sorted(missing)}")

    results = []
    try:
        for entry in entries:
            results.append(_handle_single(db, entry, act, user_id, notes))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Errore bulk: {e}")
    return {"ok": True, "handled": len(results), "results": results}


@router.post("/api/anomalies/{anomaly_id}/dismiss", dependencies=[RequireHandleAnomalies])
async def dismiss_anomaly(
    request: Request,
    anomaly_id: int,
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Chiudi anomalia senza applicare azione (falso positivo o gestita altrove)."""
    entry = (
        db.query(AnomalyEntry)
        .filter(AnomalyEntry.id == anomaly_id, AnomalyEntry.tenant_id == current_tenant_id())
        .first()
    )
    if not entry:
        raise HTTPException(404, "Anomalia non trovata")
    if entry.status != AnomalyStatus.open:
        raise HTTPException(409, f"Anomalia non è open (status={entry.status.value})")
    user = current_user_optional(request)
    entry.status = AnomalyStatus.dismissed
    entry.handled_at = datetime.utcnow()
    entry.handled_by_user_id = user.id if user else None
    if notes:
        entry.notes = (entry.notes or "") + f"\n[dismiss {datetime.utcnow().isoformat()}] {notes}"
    db.commit()
    return {"ok": True, "id": entry.id, "status": entry.status.value}


@router.post("/api/anomalies/{anomaly_id}/reopen", dependencies=[RequireHandleAnomalies])
async def reopen_anomaly(
    request: Request,
    anomaly_id: int,
    db: Session = Depends(get_db),
):
    """Riapri anomalia (handled/dismissed → open). Conserva audit dell'azione
    precedente in notes; resetta status/handled_*."""
    entry = (
        db.query(AnomalyEntry)
        .filter(AnomalyEntry.id == anomaly_id, AnomalyEntry.tenant_id == current_tenant_id())
        .first()
    )
    if not entry:
        raise HTTPException(404, "Anomalia non trovata")
    if entry.status == AnomalyStatus.open:
        return {"ok": True, "id": entry.id, "status": "open", "noop": True}
    prev_action = entry.handled_action.value if entry.handled_action else "—"
    entry.notes = (entry.notes or "") + (
        f"\n[reopen {datetime.utcnow().isoformat()}] precedente: status={entry.status.value} "
        f"action={prev_action} target_id={entry.handled_target_id}"
    )
    entry.status = AnomalyStatus.open
    entry.handled_action = None
    entry.handled_at = None
    # NB: handled_target_id resta per audit (puntatore al record creato in passato).
    db.commit()
    return {"ok": True, "id": entry.id, "status": "open"}
