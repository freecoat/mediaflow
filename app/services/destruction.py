"""app/services/destruction.py
F6 (spec 2026-06-12) — Distruzione asset documentata con doppia conferma (TPN).

FSM: requested → approved → done | rejected | cancelled (terminali immutabili).
Doppia conferma: l'approvatore deve essere DIVERSO dal richiedente (qui nel
service); il gate RBAC sul permesso `approve_destruction` sta nel router.
Il record Asset NON muore mai: content_state=deleted (o archived_only se
restano copie su tape), storia permanente via AssetMovement destroyed.
Flush senza commit — il caller decide quando committare.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    AgentJob,
    AgentJobType,
    Asset,
    AssetContentState,
    AssetMovement,
    AssetMovementType,
    DestructionRequest,
)
from app.services.agent_queue import enqueue_job
from app.services.archive_tickets import _active_lto_membership
from app.services.clock import now_utc
from app.services.notifications import notify, notify_permission

# Transizioni legali FSM: {stato_corrente: set degli stati ammessi}
_TRANSITIONS: dict[str, set[str]] = {
    "requested": {"approved", "rejected", "cancelled"},
    "approved":  {"done", "cancelled"},
    "done":      set(),
    "rejected":  set(),
    "cancelled": set(),
}

# Stati che contano come richiesta ANCORA ATTIVA sullo stesso asset
_ACTIVE = ("requested", "approved")

# Stati terminali
_TERMINAL = {"done", "rejected", "cancelled"}


def _asset_label(db: Session, asset_id: int) -> str:
    """Nome leggibile dell'asset per titoli notifica."""
    asset = db.get(Asset, asset_id)
    if asset:
        return asset.original_name or asset.filename
    return f"Asset #{asset_id}"


def _check_transition(req: DestructionRequest, new_status: str) -> None:
    """Solleva ValueError se la transizione non è permessa dalla FSM."""
    allowed = _TRANSITIONS.get(req.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Transizione non permessa: {req.status!r} → {new_status!r}. "
            f"Permesse: {sorted(allowed) or 'nessuna (stato terminale)'}"
        )


def request_destruction(
    db: Session,
    *,
    asset: Asset,
    reason: str,
    user_id: Optional[int] = None,
    tenant_id: int = 1,
) -> DestructionRequest:
    """Crea una richiesta di distruzione e notifica gli approvatori.

    Raises:
        ValueError: reason vuota, o richiesta attiva (requested/approved)
                    già esistente per lo stesso asset.
    """
    if not reason or not reason.strip():
        raise ValueError("Motivazione (reason) obbligatoria per la distruzione (TPN audit).")
    reason = reason.strip()

    existing = db.execute(
        select(DestructionRequest).where(
            DestructionRequest.asset_id == asset.id,
            DestructionRequest.tenant_id == tenant_id,
            DestructionRequest.status.in_(_ACTIVE),
        )
    ).scalars().first()
    if existing is not None:
        raise ValueError(
            f"Esiste già una richiesta di distruzione attiva (#{existing.id}, "
            f"status={existing.status!r}) per l'asset #{asset.id}."
        )

    req = DestructionRequest(
        tenant_id=tenant_id,
        asset_id=asset.id,
        reason=reason,
        requested_by_user_id=user_id,
    )
    db.add(req)
    db.flush()

    label = _asset_label(db, asset.id)
    notify_permission(
        db,
        permission="approve_destruction",
        kind="destruction_request",
        title=f"Richiesta distruzione: {label}",
        link="/storage",
        body=reason,
        actor_user_id=user_id,
        tenant_id=tenant_id,
        commit=False,
    )
    return req


def approve(
    db: Session,
    req: DestructionRequest,
    *,
    user_id: Optional[int] = None,
) -> DestructionRequest:
    """Approva la richiesta (doppia conferma).

    Il gate RBAC `approve_destruction` sta nel router; qui SOLO l'invariante
    approvatore ≠ richiedente.

    Raises:
        ValueError: stato ≠ requested, o user_id == requested_by_user_id.
    """
    _check_transition(req, "approved")
    # user_id None NON bypassa la doppia conferma: serve un approvatore reale
    if user_id is None or user_id == req.requested_by_user_id:
        raise ValueError(
            "Doppia conferma: serve un approvatore diverso dal richiedente."
        )
    req.status = "approved"
    req.approved_by_user_id = user_id
    db.flush()
    return req


def reject(
    db: Session,
    req: DestructionRequest,
    *,
    user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> DestructionRequest:
    """Rifiuta la richiesta (solo da requested). Notifica il richiedente.

    Raises:
        ValueError: stato ≠ requested.
    """
    _check_transition(req, "rejected")
    req.status = "rejected"
    req.closed_at = now_utc()
    req.closed_by_user_id = user_id

    if req.requested_by_user_id:
        label = _asset_label(db, req.asset_id)
        notify(
            db,
            user_ids=[req.requested_by_user_id],
            kind="destruction_request",
            title=f"Distruzione rifiutata: {label}",
            link="/storage",
            body=reason,
            actor_user_id=user_id,
            tenant_id=req.tenant_id,
            commit=False,
        )
    db.flush()
    return req


def execute_manual(
    db: Session,
    req: DestructionRequest,
    *,
    user_id: Optional[int] = None,
) -> DestructionRequest:
    """Chiude la richiesta come eseguita a mano (solo da approved).

    Raises:
        ValueError: stato ≠ approved.
    """
    if req.status != "approved":
        raise ValueError(
            f"execute_manual richiede status 'approved', "
            f"corrente: {req.status!r}."
        )
    req.executed_method = "manual"
    return _finalize(db, req, user_id=user_id)


def enqueue_verify(
    db: Session,
    req: DestructionRequest,
    *,
    user_id: Optional[int] = None,
) -> AgentJob:
    """Accoda il job agent `delete_verify` (solo da approved, asset registrato).

    L'agent NON cancella mai: verifica solo che il file non esista più sul
    volume. La richiesta resta approved fino all'esito.

    Raises:
        ValueError: stato ≠ approved, o asset senza volume/rel_path registrati.
    """
    if req.status != "approved":
        raise ValueError(
            f"enqueue_verify richiede status 'approved', "
            f"corrente: {req.status!r}."
        )
    asset = db.get(Asset, req.asset_id)
    if asset is None or not asset.storage_volume_id or not asset.rel_path:
        raise ValueError(
            f"Asset #{req.asset_id} non registrato su volume (storage_volume_id/"
            "rel_path mancanti). Registrare l'asset tramite agent scan prima "
            "della verifica."
        )
    job = enqueue_job(
        db,
        tenant_id=req.tenant_id,
        type=AgentJobType.delete_verify,
        payload={
            "volume_id": asset.storage_volume_id,
            "rel_path": asset.rel_path,
            "request_id": req.id,
        },
        requested_by_user_id=user_id,
        asset_id=asset.id,
    )
    req.agent_job_id = job.id
    req.executed_method = "agent_verify"
    db.flush()
    return job


def apply_verify_result(db: Session, job: AgentJob, result: dict) -> DestructionRequest:
    """Gestisce l'esito positivo di un AgentJob delete_verify.

    exists=False → il file non c'è più: finalizza come execute_manual.
    exists=True → file ancora presente: resta approved + notifica richiedente.
    Chiamato da process_job_result in agent_api.py.

    Raises:
        ValueError: richiesta non trovata o già chiusa.
    """
    req = _resolve_request(db, job)
    if req.status in _TERMINAL:
        raise ValueError(
            f"Richiesta #{req.id} già chiusa (status={req.status!r}). "
            "apply_verify_result ignorato."
        )

    if result.get("exists") is False:
        return _finalize(db, req, user_id=None)

    # File ancora presente sul volume: nessuna finalizzazione
    if req.requested_by_user_id:
        label = _asset_label(db, req.asset_id)
        notify(
            db,
            user_ids=[req.requested_by_user_id],
            kind="destruction_request",
            title=f"File ancora presente sul volume: {label}",
            link="/storage",
            body="La verifica agent ha trovato il file ancora sul volume: "
                 "cancellarlo e rilanciare la verifica.",
            tenant_id=req.tenant_id,
            commit=False,
        )
    db.flush()
    return req


def apply_verify_failure(db: Session, job: AgentJob, error: str) -> DestructionRequest:
    """Gestisce l'esito negativo di un AgentJob delete_verify.

    La richiesta resta approved; il richiedente viene notificato.
    Chiamato da process_job_result in agent_api.py.

    Raises:
        ValueError: richiesta non trovata o già chiusa.
    """
    req = _resolve_request(db, job)
    if req.status in _TERMINAL:
        raise ValueError(
            f"Richiesta #{req.id} già chiusa (status={req.status!r}). "
            "apply_verify_failure ignorato."
        )
    if req.requested_by_user_id:
        label = _asset_label(db, req.asset_id)
        notify(
            db,
            user_ids=[req.requested_by_user_id],
            kind="destruction_request",
            title=f"Verifica distruzione fallita: {label}",
            link="/storage",
            body=(error or "")[:500],
            tenant_id=req.tenant_id,
            commit=False,
        )
    db.flush()
    return req


def transition(
    db: Session,
    req: DestructionRequest,
    new_status: str,
    *,
    user_id: Optional[int] = None,
    is_admin: bool = False,
) -> DestructionRequest:
    """Transizione generica — supporta SOLO 'cancelled' (da requested/approved).

    approve/reject/execute hanno funzioni dedicate con le loro invarianti.
    Spec: cancelled SOLO dal richiedente o da un admin (is_admin dal router).

    Raises:
        ValueError: transizione non permessa, o stato gestito da funzione dedicata.
    """
    _check_transition(req, new_status)
    if new_status != "cancelled":
        raise ValueError(
            f"Stato {new_status!r}: usare la funzione dedicata "
            "(approve/reject/execute_manual)."
        )
    if (not is_admin
            and req.requested_by_user_id is not None
            and user_id != req.requested_by_user_id):
        raise ValueError(
            "Annullamento consentito solo al richiedente originale o a un admin."
        )
    req.status = "cancelled"
    req.closed_at = now_utc()
    req.closed_by_user_id = user_id
    db.flush()
    return req


# ── helpers interni ───────────────────────────────────────────────────

def _finalize(
    db: Session,
    req: DestructionRequest,
    *,
    user_id: Optional[int] = None,
) -> DestructionRequest:
    """Finalizza la distruzione: movimento destroyed + content_state + notifica.

    content_state: membership tape ATTIVE presenti → archived_only (copie
    residue su LTO), altrimenti deleted. Il record Asset resta (storia TPN).
    """
    if req.status == "done":
        return req  # idempotente: niente doppio movimento su race manual/verify
    asset = db.get(Asset, req.asset_id)

    mv = AssetMovement(
        tenant_id=req.tenant_id,
        asset_id=req.asset_id,
        movement_type=AssetMovementType.destroyed,
        contents_description=req.reason,
    )
    db.add(mv)

    if asset is not None:
        m = _active_lto_membership(db, req.asset_id, tenant_id=req.tenant_id)
        asset.content_state = (
            AssetContentState.archived_only if m is not None
            else AssetContentState.deleted
        )

    req.status = "done"
    req.closed_at = now_utc()
    req.closed_by_user_id = user_id

    if req.requested_by_user_id:
        label = _asset_label(db, req.asset_id)
        notify(
            db,
            user_ids=[req.requested_by_user_id],
            kind="destruction_request",
            title=f"Distruzione completata: {label}",
            link="/storage",
            body=req.reason,
            actor_user_id=user_id,
            tenant_id=req.tenant_id,
            commit=False,
        )
    db.flush()
    return req


def _resolve_request(db: Session, job: AgentJob) -> DestructionRequest:
    """Risolve la DestructionRequest dall'agent_job_id. ValueError se assente."""
    row = db.execute(
        select(DestructionRequest).where(
            DestructionRequest.agent_job_id == job.id,
            DestructionRequest.tenant_id == job.tenant_id,
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(
            f"Nessuna DestructionRequest trovata per agent_job_id={job.id}."
        )
    return row
