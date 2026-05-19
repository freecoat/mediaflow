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
    JobCostLine,
    LossEntry,
    LossReason,
    OverheadCost,
    OverheadCostCategory,
    PriceItem,
    Project,
    User,
)
from app.services.anomaly_detector import detect_all
from app.services.notifications import notify
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
    department_id: Optional[int] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    db: Session = Depends(get_db),
):
    """Lista anomalie con filtri. Default: solo open.

    v3.5.0-alpha.141 — Filtro `department_id`: applicato solo a anomalie
    con source_kind='jcl' tramite join JCL→price_item.department_id.
    Anomalie su altre source (quote/job/invoice) NON sono filtrate dal dept
    (perché non hanno reparto diretto). Per ora il filtro le esclude.
    """
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
    # v3.5.0-alpha.170 — Fallback robusto: anomalie create prima dei detector
    # post-α.89 (o casi degenerati) possono avere client_id/project_id=NULL
    # nonostante il job_id sia popolato. Senza fallback il filtro non
    # ritornava nulla. Ora usiamo OR con subquery: match diretto OR derivato
    # via Job.
    from sqlalchemy import or_
    if project_id:
        job_ids_in_proj = db.query(Job.id).filter(Job.project_id == project_id).subquery()
        q = q.filter(or_(
            AnomalyEntry.project_id == project_id,
            AnomalyEntry.job_id.in_(job_ids_in_proj),
        ))
    if client_id:
        job_ids_for_client = db.query(Job.id).filter(Job.client_id == client_id).subquery()
        q = q.filter(or_(
            AnomalyEntry.client_id == client_id,
            AnomalyEntry.job_id.in_(job_ids_for_client),
        ))
    if department_id:
        # Subquery JCL del dipartimento richiesto via price_item.department_id
        from sqlalchemy import select
        dept_jcl_ids = select(JobCostLine.id).join(
            PriceItem, PriceItem.id == JobCostLine.price_item_id
        ).where(PriceItem.department_id == department_id)
        q = q.filter(
            AnomalyEntry.source_kind == AnomalySourceKind.jcl,
            AnomalyEntry.source_id.in_(dept_jcl_ids),
        )
    if from_date:
        q = q.filter(AnomalyEntry.detected_at >= datetime.combine(from_date, datetime.min.time()))
    if to_date:
        q = q.filter(AnomalyEntry.detected_at <= datetime.combine(to_date, datetime.max.time()))
    rows = q.order_by(AnomalyEntry.detected_at.desc()).all()
    return [_to_dict(a) for a in rows]


@router.get("/api/anomalies/v2/summary", dependencies=[RequireViewAnomalies])
async def summary_anomalies(
    project_id: Optional[int] = None,
    client_id: Optional[int] = None,
    department_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """KPI per dashboard: conteggi e totale € per tipo, solo open.

    v3.5.0-alpha.170 — Accetta gli stessi filtri di /v2 (project_id, client_id,
    department_id). I chip in UI ora riflettono il contesto del filtro,
    pre-α.170 mostravano sempre il totale aggregato (bug segnalato Matteo).
    """
    from sqlalchemy import func, or_
    q = db.query(
            AnomalyEntry.anomaly_type,
            func.count(AnomalyEntry.id).label("n"),
            func.sum(AnomalyEntry.amount).label("total"),
        ).filter(
            AnomalyEntry.tenant_id == current_tenant_id(),
            AnomalyEntry.status == AnomalyStatus.open,
        )
    if project_id:
        job_ids_in_proj = db.query(Job.id).filter(Job.project_id == project_id).subquery()
        q = q.filter(or_(
            AnomalyEntry.project_id == project_id,
            AnomalyEntry.job_id.in_(job_ids_in_proj),
        ))
    if client_id:
        job_ids_for_client = db.query(Job.id).filter(Job.client_id == client_id).subquery()
        q = q.filter(or_(
            AnomalyEntry.client_id == client_id,
            AnomalyEntry.job_id.in_(job_ids_for_client),
        ))
    if department_id:
        from sqlalchemy import select
        dept_jcl_ids = select(JobCostLine.id).join(
            PriceItem, PriceItem.id == JobCostLine.price_item_id
        ).where(PriceItem.department_id == department_id)
        q = q.filter(
            AnomalyEntry.source_kind == AnomalySourceKind.jcl,
            AnomalyEntry.source_id.in_(dept_jcl_ids),
        )
    rows = q.group_by(AnomalyEntry.anomaly_type).all()
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
    target_user_id: Optional[int] = None,
    next_action_label: Optional[str] = None,
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
        # v3.5.0-alpha.114 A8: delego al generatore canonico in overhead._next_code
        # che gestisce soft-delete bypass (era duplicato e poteva divergere).
        from app.routers.overhead import _next_code
        year = datetime.utcnow().year
        code = _next_code(db, year)
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

    # v3.5.0-alpha.141 — rimanda_commerciale / rivaluta_producer: cambio stato
    # workflow + Notification al destinatario specifico se target_user_id fornito.
    # Title = "[Anomalia] {tipo}". Body = description + msg operatore + next_action.
    if action in (AnomalyAction.rimanda_commerciale, AnomalyAction.rivaluta_producer):
        if target_user_id:
            type_lbl = entry.anomaly_type.value if entry.anomaly_type else "?"
            action_lbl = ("Rimanda al commerciale" if action == AnomalyAction.rimanda_commerciale
                          else "Rivaluta producer")
            body_parts = [f"Anomalia #{entry.id} ({type_lbl}): {entry.description or '(no desc)'}"]
            if entry.project_id:
                body_parts.append(f"Progetto #{entry.project_id}" + (f" — {entry.project.title}" if entry.project else ""))
            if entry.amount:
                body_parts.append(f"Importo: €{entry.amount:.2f}")
            if notes:
                body_parts.append(f"\nMessaggio: {notes}")
            if next_action_label:
                body_parts.append(f"\nAzione richiesta: {next_action_label}")
            link = (f"/projects/{entry.project_id}" if entry.project_id
                    else f"/finance#section-anomalies")
            notify(
                db,
                user_ids=[target_user_id],
                kind="custom",
                title=f"[{action_lbl}] Anomalia #{entry.id}",
                body="\n".join(body_parts),
                severity="action_required",
                link=link,
                actor_user_id=user_id,
                tenant_id=current_tenant_id(),
                commit=False,  # commit gestito dal caller (handle_anomaly)
            )
            target_kind = "Notification"
            target_id = target_user_id  # snapshot dell'utente notificato
        else:
            # Workflow audit-only, no Notification
            pass

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
    # v3.5.0-alpha.141 — Per rimanda/rivaluta: destinatario + azione successiva.
    target_user_id: Optional[int] = Form(None),
    next_action_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Applica azione su singola anomalia. Per rimanda/rivaluta, opzionale
    target_user_id (destinatario Notification) + next_action_label (es. "modifica
    quote", "ricontatta cliente", "riallinea pianificazione")."""
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
    result = _handle_single(
        db, entry, act, user.id if user else None, notes,
        target_user_id=target_user_id, next_action_label=next_action_label,
    )
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
