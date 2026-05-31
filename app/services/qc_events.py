"""
v3.5.0-alpha.172.98 (Bundle L Stack 2) — QC events service layer.

Public API per scrivere eventi nello stream QCEvent. Tutte le funzioni:
- Risolvono qc_number e sequence automaticamente (no race-condition se chiamate
  in serie nella stessa session — il flush incrementa entrambi).
- Ritornano l'oggetto QCEvent creato (gia' flushato).
- Lasciano il commit al caller (services compone, router commita).

Payload suggerito per ogni event_type (dict libero, no validation runtime):

| event_type             | payload_json shape                                         |
|------------------------|------------------------------------------------------------|
| qc_started             | {qc_number, asset_id?, refresh_snapshot: bool}             |
| snapshot_taken         | {asset_id, tech_specs_json, extractor, schema_version}     |
| video_error_logged     | {timecode, grade (1-4), description, reference?}           |
| audio_error_logged     | {timecode, grade, channel, description}                    |
| text_error_logged      | {timecode, grade, language, description}                   |
| recommendation_added   | {description, applies_to?}                                 |
| note_added             | {text}                                                     |
| correction_requested   | {target_event_ids: [...], description, due_date?}          |
| signoff_added          | {signer_id, role: qc_lead|client|director, note?}          |
| qc_passed              | {overall_grade?, note?}                                    |
| qc_failed              | {primary_cause, max_grade}                                 |
| qc_conditional         | {conditions: [...], pass_when?}                            |
| qc_reopened            | {reason, previous_qc_number}                               |
"""
from __future__ import annotations
from app.services.clock import now_utc

from datetime import datetime, timedelta
from typing import Optional, Any

from sqlalchemy.orm import Session

from app.models.models import (
    QCEvent, QCEventType, JobDeliverable, Tenant,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _next_sequence(sess: Session, deliverable_id: int, qc_number: int) -> int:
    """Prossima sequence (1-based) per (deliverable, qc_number)."""
    last = (
        sess.query(QCEvent.sequence)
        .filter(
            QCEvent.deliverable_id == deliverable_id,
            QCEvent.qc_number == qc_number,
        )
        .order_by(QCEvent.sequence.desc())
        .first()
    )
    return (last[0] if last else 0) + 1


def _current_qc_number(sess: Session, deliverable_id: int) -> int:
    """qc_number attivo per il deliverable (= ultimo qc_started). 0 se mai
    iniziato."""
    last_started = (
        sess.query(QCEvent.qc_number)
        .filter(
            QCEvent.deliverable_id == deliverable_id,
            QCEvent.event_type == QCEventType.qc_started,
        )
        .order_by(QCEvent.qc_number.desc())
        .first()
    )
    return last_started[0] if last_started else 0


def _emit(
    sess: Session,
    *,
    deliverable_id: int,
    tenant_id: int,
    qc_number: int,
    event_type: QCEventType,
    payload: dict,
    operator_id: Optional[int] = None,
    asset_id: Optional[int] = None,
    source: str = "manual",
    source_excel_path: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
) -> QCEvent:
    seq = _next_sequence(sess, deliverable_id, qc_number)
    ev = QCEvent(
        tenant_id=tenant_id,
        deliverable_id=deliverable_id,
        asset_id=asset_id,
        qc_number=qc_number,
        sequence=seq,
        event_type=event_type,
        payload_json=payload or {},
        operator_id=operator_id,
        occurred_at=occurred_at or now_utc(),
        source=source,
        source_excel_path=source_excel_path,
    )
    sess.add(ev)
    sess.flush()  # necessario per ev.id popolato
    # Projection sync esplicita (evita ambiguita' SQLAlchemy after_insert listener).
    from app.services.qc_event_listener import apply_projection_for_event
    apply_projection_for_event(sess, ev)
    return ev


def _resolve_tenant(sess: Session, deliverable_id: int) -> int:
    """Risolvi tenant_id dal deliverable per evitare argument boilerplate."""
    deliv = sess.query(JobDeliverable).filter(JobDeliverable.id == deliverable_id).first()
    if deliv is None:
        raise ValueError(f"JobDeliverable#{deliverable_id} non trovato")
    return deliv.tenant_id


def _tech_specs_refresh_days(sess: Session, tenant_id: int) -> int:
    t = sess.query(Tenant).filter(Tenant.id == tenant_id).first()
    return (t.tech_specs_refresh_days if t else 30) or 30


# ── Public API ─────────────────────────────────────────────────────────────

def start_qc(
    sess: Session,
    deliverable_id: int,
    *,
    asset_id: Optional[int] = None,
    operator_id: Optional[int] = None,
    source: str = "manual",
    refresh_snapshot: bool = True,
) -> tuple[QCEvent, Optional[QCEvent]]:
    """Apre un nuovo round QC. Incrementa qc_number. Se asset_id e
    refresh_snapshot=True, cristallizza tech_specs in QCEvent snapshot_taken.

    Ritorna (qc_started_event, snapshot_event | None).
    """
    tenant_id = _resolve_tenant(sess, deliverable_id)
    cur_qc = _current_qc_number(sess, deliverable_id)
    new_qc = cur_qc + 1

    started = _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=new_qc,
        event_type=QCEventType.qc_started,
        payload={
            "qc_number": new_qc,
            "asset_id": asset_id,
            "refresh_snapshot": refresh_snapshot,
        },
        operator_id=operator_id,
        asset_id=asset_id,
        source=source,
    )

    # Snapshot: se asset_id presente, carica Asset.tech_specs_json. Se stale
    # (> tech_specs_refresh_days), il caller dovrebbe ri-estrarre prima via
    # tech_specs_extractor; qui registriamo il valore corrente.
    snap = None
    if asset_id is not None:
        from app.models.models import Asset
        asset = sess.query(Asset).filter(Asset.id == asset_id).first()
        if asset is not None and asset.tech_specs_json:
            snap = _emit(
                sess,
                deliverable_id=deliverable_id,
                tenant_id=tenant_id,
                qc_number=new_qc,
                event_type=QCEventType.snapshot_taken,
                payload={
                    "asset_id": asset_id,
                    "tech_specs_json": asset.tech_specs_json,
                    "extractor": asset.tech_specs_extractor,
                    "schema_version": asset.tech_specs_schema_version
                        if hasattr(asset, "tech_specs_schema_version") else None,
                    "extracted_at": asset.tech_specs_extracted_at.isoformat()
                        if asset.tech_specs_extracted_at else None,
                    "stale": _is_stale(asset.tech_specs_extracted_at,
                                       _tech_specs_refresh_days(sess, tenant_id)),
                },
                operator_id=operator_id,
                asset_id=asset_id,
                source=source,
            )
    return started, snap


def _is_stale(extracted_at: Optional[datetime], refresh_days: int) -> bool:
    if extracted_at is None:
        return True
    return (now_utc() - extracted_at) > timedelta(days=refresh_days)


def log_error(
    sess: Session,
    deliverable_id: int,
    *,
    channel: str,  # "video" | "audio" | "text"
    timecode: Optional[str] = None,
    grade: int = 1,
    description: str = "",
    extra: Optional[dict] = None,
    operator_id: Optional[int] = None,
    source: str = "manual",
) -> QCEvent:
    """Logga un errore QC. `channel` mappa a event_type:
    video → video_error_logged, audio → audio_error_logged, text → text_error_logged."""
    chan = (channel or "").lower()
    mapping = {
        "video": QCEventType.video_error_logged,
        "audio": QCEventType.audio_error_logged,
        "text":  QCEventType.text_error_logged,
    }
    et = mapping.get(chan)
    if et is None:
        raise ValueError(f"channel non valido: {channel} (atteso video|audio|text)")

    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError(
            f"Nessun QC attivo per deliverable#{deliverable_id}. "
            "Chiamare start_qc() prima di log_error()."
        )

    payload = {
        "timecode": timecode,
        "grade": int(grade) if grade else 1,
        "description": description or "",
    }
    if extra:
        payload.update(extra)
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=et,
        payload=payload,
        operator_id=operator_id,
        source=source,
    )


def add_recommendation(
    sess: Session,
    deliverable_id: int,
    description: str,
    *,
    applies_to: Optional[Any] = None,
    operator_id: Optional[int] = None,
) -> QCEvent:
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError("Nessun QC attivo: chiama start_qc() prima.")
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.recommendation_added,
        payload={"description": description, "applies_to": applies_to},
        operator_id=operator_id,
    )


def add_note(
    sess: Session,
    deliverable_id: int,
    text: str,
    *,
    operator_id: Optional[int] = None,
) -> QCEvent:
    """Note libere. Non richiedono un QC attivo (utile per pre-QC kickoff)."""
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        qc_num = 1  # nota pre-QC: usa il futuro qc 1 come container
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.note_added,
        payload={"text": text or ""},
        operator_id=operator_id,
    )


def request_correction(
    sess: Session,
    deliverable_id: int,
    *,
    target_event_ids: list[int],
    description: str,
    due_date: Optional[str] = None,
    operator_id: Optional[int] = None,
) -> QCEvent:
    """Richiede correzione su uno o piu' eventi (tipicamente video/audio/text
    errors). target_event_ids permette al QC operator di raggruppare errors da
    fixare insieme."""
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError("Nessun QC attivo: chiama start_qc() prima.")
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.correction_requested,
        payload={
            "target_event_ids": list(target_event_ids or []),
            "description": description,
            "due_date": due_date,
        },
        operator_id=operator_id,
    )


def signoff(
    sess: Session,
    deliverable_id: int,
    *,
    signer_id: int,
    role: str = "qc_lead",  # "qc_lead" | "client" | "director" | "supervisor"
    note: Optional[str] = None,
    operator_id: Optional[int] = None,
) -> QCEvent:
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError("Nessun QC attivo: chiama start_qc() prima.")
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.signoff_added,
        payload={
            "signer_id": signer_id,
            "role": role,
            "note": note,
        },
        operator_id=operator_id or signer_id,
    )


def pass_qc(
    sess: Session,
    deliverable_id: int,
    *,
    overall_grade: Optional[int] = None,
    note: Optional[str] = None,
    operator_id: Optional[int] = None,
    source: str = "manual",
) -> QCEvent:
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError("Nessun QC attivo da chiudere.")
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.qc_passed,
        payload={"overall_grade": overall_grade, "note": note},
        operator_id=operator_id,
        source=source,
    )


def fail_qc(
    sess: Session,
    deliverable_id: int,
    *,
    primary_cause: str,
    max_grade: Optional[int] = None,
    operator_id: Optional[int] = None,
    source: str = "manual",
) -> QCEvent:
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError("Nessun QC attivo da chiudere.")
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.qc_failed,
        payload={"primary_cause": primary_cause, "max_grade": max_grade},
        operator_id=operator_id,
        source=source,
    )


def conditional_qc(
    sess: Session,
    deliverable_id: int,
    *,
    conditions: list[str],
    pass_when: Optional[str] = None,
    operator_id: Optional[int] = None,
    source: str = "manual",
) -> QCEvent:
    """QC pass condizionato: il deliverable e' tecnicamente accettabile a patto
    di soddisfare le `conditions`. Es. "fix minore loudness master prima di
    delivery". qc_substatus mappato a `passed` per back-compat Bundle I."""
    tenant_id = _resolve_tenant(sess, deliverable_id)
    qc_num = _current_qc_number(sess, deliverable_id)
    if qc_num == 0:
        raise ValueError("Nessun QC attivo da chiudere.")
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=qc_num,
        event_type=QCEventType.qc_conditional,
        payload={
            "conditions": list(conditions or []),
            "pass_when": pass_when,
        },
        operator_id=operator_id,
        source=source,
    )


def reopen_qc(
    sess: Session,
    deliverable_id: int,
    *,
    reason: str,
    operator_id: Optional[int] = None,
) -> QCEvent:
    """Riapre un deliverable il cui ultimo QC era passed/failed/conditional.
    Registra `qc_reopened` con il qc_number precedente. Il prossimo start_qc()
    incrementera' il qc_number."""
    tenant_id = _resolve_tenant(sess, deliverable_id)
    prev_qc = _current_qc_number(sess, deliverable_id)
    if prev_qc == 0:
        raise ValueError(
            f"deliverable#{deliverable_id} non ha QC pregressi da riaprire."
        )
    return _emit(
        sess,
        deliverable_id=deliverable_id,
        tenant_id=tenant_id,
        qc_number=prev_qc,
        event_type=QCEventType.qc_reopened,
        payload={"reason": reason, "previous_qc_number": prev_qc},
        operator_id=operator_id,
    )


def rebuild_qc_report(sess: Session, deliverable_id: int):
    """Re-export del rebuild_qc_report del listener module per ergonomia
    (`from app.services.qc_events import rebuild_qc_report`)."""
    from app.services.qc_event_listener import rebuild_qc_report as _rb
    return _rb(sess, deliverable_id)
