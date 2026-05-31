"""
v3.5.0-alpha.172.98 (Bundle L Stack 2) — QCEvent listener.

Tre responsabilità:
1. Immutability: QCEvent non puo' essere UPDATED ne' DELETED dall'app.
   `before_update` e `before_delete` listener rifiutano. Eccezione: session
   option `__qc_admin_override__=True` per super-admin operations.
2. Projection sync: dopo INSERT di un QCEvent, ricalcola la row QCReport per
   quel deliverable (counter incrementali via lookup `event_type`).
3. Bundle I sync: aggiorna `JobDeliverable.qc_substatus` + `qc_run_at` +
   `qc_run_by_user_id` per coerenza con cascade workflow esistente.

Init in `app/main.py` lifespan via `init_qc_event_listeners()`.
"""
from __future__ import annotations
from app.services.clock import now_utc

from datetime import datetime
from typing import Optional

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.models.models import (
    QCEvent, QCReport, QCEventType,
    JobDeliverable, QCSubstatus, DeliverableStatus,
)


class QCEventImmutabilityError(Exception):
    """Raised when an UPDATE/DELETE is attempted on a QCEvent row outside of
    the admin override path."""


def _is_admin_override(session: Optional[Session]) -> bool:
    """Check session info for `__qc_admin_override__=True`. Used by super-admin
    repair scripts that must rewrite the event stream (es. correzione manuale
    di un bug di backfill). Settabile via session.info['__qc_admin_override__'] = True."""
    if session is None:
        return False
    try:
        return bool(session.info.get("__qc_admin_override__"))
    except Exception:
        return False


def _block_update(mapper, connection, target):
    """before_update listener — block unless admin override."""
    # Best-effort lookup della session corrente (connection.info propaga
    # session.info attraverso execute options).
    sess = None
    try:
        from sqlalchemy.orm.session import object_session
        sess = object_session(target)
    except Exception:
        pass
    if _is_admin_override(sess):
        return
    raise QCEventImmutabilityError(
        f"QCEvent#{target.id} UPDATE blocked: append-only table. "
        "Set session.info['__qc_admin_override__']=True per superare il guard."
    )


def _block_delete(mapper, connection, target):
    sess = None
    try:
        from sqlalchemy.orm.session import object_session
        sess = object_session(target)
    except Exception:
        pass
    if _is_admin_override(sess):
        return
    raise QCEventImmutabilityError(
        f"QCEvent#{target.id} DELETE blocked: append-only table. "
        "Set session.info['__qc_admin_override__']=True per superare il guard."
    )


# ── Projection sync ─────────────────────────────────────────────────────────

_COUNTER_FIELD_BY_EVENT = {
    QCEventType.video_error_logged: "video_errors_count",
    QCEventType.audio_error_logged: "audio_errors_count",
    QCEventType.text_error_logged: "text_errors_count",
    QCEventType.recommendation_added: "recommendations_count",
    QCEventType.note_added: "notes_count",
    QCEventType.correction_requested: "open_corrections_count",
    QCEventType.signoff_added: "signoffs_count",
}

# QCEvent.event_type → (QCReport.overall_status, JobDeliverable.qc_substatus)
# `conditional` mappato a passed in qc_substatus (back-compat Bundle I 3-valori).
# UI rich legge QCReport.overall_status per distinguere conditional da passed.
_TERMINAL_MAPPING = {
    QCEventType.qc_passed:      ("passed",      QCSubstatus.passed),
    QCEventType.qc_failed:      ("failed",      QCSubstatus.rejected),
    QCEventType.qc_conditional: ("conditional", QCSubstatus.passed),
}


def _ensure_report(sess: Session, deliverable_id: int, tenant_id: int) -> QCReport:
    rep = sess.query(QCReport).filter(QCReport.deliverable_id == deliverable_id).first()
    if rep is None:
        rep = QCReport(
            tenant_id=tenant_id,
            deliverable_id=deliverable_id,
            last_qc_number=0,
            overall_status="in_progress",
        )
        sess.add(rep)
        sess.flush()
    return rep


def _apply_event_to_report(sess: Session, ev: QCEvent) -> None:
    """Increment counters + update overall_status based on event_type."""
    rep = _ensure_report(sess, ev.deliverable_id, ev.tenant_id)

    rep.last_event_at = ev.occurred_at
    rep.last_event_id = ev.id
    rep.last_operator_id = ev.operator_id

    et = ev.event_type
    if et == QCEventType.qc_started:
        rep.last_qc_number = max(rep.last_qc_number or 0, ev.qc_number)
        rep.overall_status = "in_progress"
    elif et == QCEventType.qc_reopened:
        # qc_reopened registra l'intento di riapertura; il prossimo qc_started
        # incrementera' last_qc_number e tornera' overall a in_progress.
        rep.overall_status = "reopened"
    elif et in _TERMINAL_MAPPING:
        new_overall, _qc_sub = _TERMINAL_MAPPING[et]
        rep.overall_status = new_overall
    else:
        # Errori, note, correction, signoff, recommendation, snapshot.
        field = _COUNTER_FIELD_BY_EVENT.get(et)
        if field is not None:
            setattr(rep, field, (getattr(rep, field) or 0) + 1)
        # max_grade per video/audio/text errors
        if et in (
            QCEventType.video_error_logged,
            QCEventType.audio_error_logged,
            QCEventType.text_error_logged,
        ):
            try:
                grade = int((ev.payload_json or {}).get("grade") or 0)
            except (TypeError, ValueError):
                grade = 0
            if grade and (rep.max_grade is None or grade > rep.max_grade):
                rep.max_grade = grade

    rep.updated_at = now_utc()


def _sync_deliverable_bundle_i(sess: Session, ev: QCEvent) -> None:
    """Aggiorna JobDeliverable.qc_substatus + qc_run_at + qc_run_by_user_id
    per back-compat Bundle I (cascade workflow + UI esistente).

    Solo sui terminal events (qc_started, qc_passed, qc_failed, qc_conditional,
    qc_reopened): tutti gli altri events sono dettagli interni che non cambiano
    lo stato visibile del deliverable.
    """
    et = ev.event_type
    if et not in (
        QCEventType.qc_started, QCEventType.qc_passed,
        QCEventType.qc_failed, QCEventType.qc_conditional,
        QCEventType.qc_reopened,
    ):
        return

    deliv = sess.query(JobDeliverable).filter(
        JobDeliverable.id == ev.deliverable_id
    ).first()
    if deliv is None:
        return

    if et == QCEventType.qc_started:
        # Forza main status -> qc + substatus -> in_progress
        deliv.status = DeliverableStatus.qc
        deliv.qc_substatus = QCSubstatus.in_progress
        deliv.qc_run_at = ev.occurred_at
        if ev.operator_id is not None:
            deliv.qc_run_by_user_id = ev.operator_id
    elif et == QCEventType.qc_reopened:
        # Riapertura: lascia main status = qc, sub torna a in_progress.
        deliv.status = DeliverableStatus.qc
        deliv.qc_substatus = QCSubstatus.in_progress
    elif et in _TERMINAL_MAPPING:
        _overall, qc_sub = _TERMINAL_MAPPING[et]
        deliv.qc_substatus = qc_sub
        deliv.qc_run_at = ev.occurred_at
        if ev.operator_id is not None:
            deliv.qc_run_by_user_id = ev.operator_id


def apply_projection_for_event(sess: Session, ev: QCEvent) -> None:
    """Applica projection sync + Bundle I sync per un singolo QCEvent.

    NON usato come SQLAlchemy listener (le modifiche fatte during after_insert
    sono problematiche: la session e' gia' in flush mode, modifiche subsequent
    al QCReport possono essere ignorate). Chiamato esplicitamente dal service
    `qc_events._emit` subito dopo `sess.flush()` del QCEvent.
    """
    try:
        _apply_event_to_report(sess, ev)
        _sync_deliverable_bundle_i(sess, ev)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            f"[qc_event_listener] projection sync failed for QCEvent#{ev.id}: {e}"
        )


# ── Public init ────────────────────────────────────────────────────────────

_LISTENERS_REGISTERED = False


def init_qc_event_listeners() -> None:
    """Idempotente: registra i listener immutability su QCEvent (before_update,
    before_delete). La projection sync (QCReport + JobDeliverable Bundle I) e'
    invece chiamata esplicitamente dal service `qc_events._emit` via
    `apply_projection_for_event` per evitare ambiguita' dello stato session
    durante after_insert."""
    global _LISTENERS_REGISTERED
    if _LISTENERS_REGISTERED:
        return
    event.listen(QCEvent, "before_update", _block_update, propagate=True)
    event.listen(QCEvent, "before_delete", _block_delete, propagate=True)
    _LISTENERS_REGISTERED = True


def rebuild_qc_report(sess: Session, deliverable_id: int) -> Optional[QCReport]:
    """Ricostruisce QCReport per un deliverable da zero leggendo lo stream
    QCEvent. Usato per refresh esplicito o dopo backfill bulk. Non passa per
    i listener (scrive direttamente sul report)."""
    events = (
        sess.query(QCEvent)
        .filter(QCEvent.deliverable_id == deliverable_id)
        .order_by(QCEvent.qc_number, QCEvent.sequence, QCEvent.id)
        .all()
    )
    if not events:
        # Niente eventi: rimuovi il QCReport se presente (idempotenza pulita).
        rep = sess.query(QCReport).filter(
            QCReport.deliverable_id == deliverable_id
        ).first()
        if rep is not None:
            sess.delete(rep)
        return None

    tenant_id = events[0].tenant_id
    rep = sess.query(QCReport).filter(QCReport.deliverable_id == deliverable_id).first()
    if rep is None:
        rep = QCReport(
            tenant_id=tenant_id,
            deliverable_id=deliverable_id,
            last_qc_number=0,
            overall_status="in_progress",
        )
        sess.add(rep)
    # Reset counters
    rep.last_qc_number = 0
    rep.overall_status = "in_progress"
    rep.video_errors_count = 0
    rep.audio_errors_count = 0
    rep.text_errors_count = 0
    rep.recommendations_count = 0
    rep.notes_count = 0
    rep.open_corrections_count = 0
    rep.signoffs_count = 0
    rep.max_grade = None
    rep.last_event_id = None
    rep.last_event_at = None
    rep.last_operator_id = None

    for ev in events:
        _apply_event_to_report(sess, ev)
    return rep
