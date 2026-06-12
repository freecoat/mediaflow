"""app/services/transfer_orders.py
F5 (spec 2026-06-12) — Service ordini di transfer digitale dalla facility.

FSM: requested → in_progress → done | failed | cancelled (terminali immutabili).
Movimenti outgest creati per ogni asset su close_order ok=True.
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
    AssetMovement,
    AssetMovementType,
    TransferOrder,
)
from app.services.agent_queue import enqueue_job
from app.services.clock import now_utc
from app.services.notifications import notify_permission
from app.services.transfer_adapters import ADAPTERS

CURRENT_TENANT = 1

# Transizioni legali FSM: {stato_corrente: set degli stati ammessi}
_TRANSITIONS: dict[str, set[str]] = {
    "requested":   {"in_progress", "done", "cancelled"},
    "in_progress": {"done", "cancelled"},
    "done":        set(),
    "failed":      set(),
    "cancelled":   set(),
}

# Stati terminali che bloccano ulteriori operazioni
_TERMINAL = {"done", "failed", "cancelled"}


def create_order(
    db: Session,
    *,
    tool: str,
    asset_ids: list[int],
    destination: str,
    recipient_email: Optional[str] = None,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
    tenant_id: int = CURRENT_TENANT,
) -> TransferOrder:
    """Crea un ordine di transfer digitale.

    Args:
        db: sessione SQLAlchemy.
        tool: chiave driver (es. "manual", "aspera").
        asset_ids: lista ≥1 di ID Asset tenant-scoped.
        destination: destinazione (non vuota; formato ascp per aspera).
        recipient_email: email contatto destinatario (opzionale).
        note: nota libera.
        user_id: utente richiedente.
        tenant_id: tenant scope.

    Returns:
        TransferOrder con status="requested" (flush senza commit).

    Raises:
        ValueError: tool sconosciuto, asset_ids vuoti, destination vuota,
                    asset non trovato nel tenant, asset senza volume/rel_path
                    per tool agent-driven.
    """
    # Validazione tool
    if tool not in ADAPTERS:
        raise ValueError(
            f"Tool sconosciuto: {tool!r}. Disponibili: {sorted(ADAPTERS)}"
        )

    # Validazione asset_ids
    if not asset_ids:
        raise ValueError("asset_ids non può essere vuoto: almeno 1 asset richiesto.")

    # Validazione destination
    if not destination or not destination.strip():
        raise ValueError("destination non può essere vuota.")
    destination = destination.strip()
    # Argument injection: la destination finisce in argv di ascp — una stringa
    # che inizia con "-" verrebbe parsata come flag dal tool.
    if destination.startswith("-"):
        raise ValueError("destination non valida: non può iniziare con '-'.")
    if ADAPTERS[tool].mode == "agent" and tool == "aspera":
        # Shape ascp: user@host:/path (almeno @ e : dopo la @)
        at = destination.find("@")
        if at <= 0 or ":" not in destination[at:]:
            raise ValueError(
                "destination aspera non valida: atteso formato user@host:/path."
            )

    # Risoluzione asset tenant-scoped
    assets: list[Asset] = []
    for aid in asset_ids:
        a = db.get(Asset, aid)
        if a is None or a.tenant_id != tenant_id:
            raise ValueError(
                f"Asset #{aid} non trovato nel tenant {tenant_id}."
            )
        assets.append(a)

    adapter = ADAPTERS[tool]

    # Per driver agent: richiede storage_volume_id + rel_path su ogni asset
    files: list[dict] = []
    if adapter.mode == "agent":
        for a in assets:
            if not a.storage_volume_id or not a.rel_path:
                raise ValueError(
                    f"Asset #{a.id} ({a.original_name or a.filename}) non ha "
                    f"storage_volume_id o rel_path registrati. "
                    "Registrare l'asset tramite agent scan prima di accodare il transfer."
                )
            files.append({"volume_id": a.storage_volume_id, "rel_path": a.rel_path})

    # Crea l'ordine
    order = TransferOrder(
        tenant_id=tenant_id,
        tool=tool,
        destination=destination,
        recipient_email=recipient_email,
        asset_ids=asset_ids,
        note=note,
        requested_by_user_id=user_id,
    )
    db.add(order)
    db.flush()  # serve l'id per il payload del job

    # Per driver agent: accoda AgentJob
    if adapter.mode == "agent":
        payload = adapter.build_job_payload(order, files)
        job = enqueue_job(
            db,
            tenant_id=tenant_id,
            type=AgentJobType.transfer,
            payload=payload,
            requested_by_user_id=user_id,
            asset_id=assets[0].id,
        )
        order.agent_job_id = job.id
        db.flush()

    return order


def close_order(
    db: Session,
    order: TransferOrder,
    *,
    ok: bool,
    method: str,
    details: Optional[str] = None,
    link_url: Optional[str] = None,
    link_expires_at=None,
    user_id: Optional[int] = None,
) -> TransferOrder:
    """Chiude l'ordine con esito positivo o negativo.

    Args:
        db: sessione SQLAlchemy.
        order: istanza TransferOrder da chiudere.
        ok: True = done, False = failed.
        method: metodo di verifica (checksum|size|manual|tool_rc).
        details: testo libero verifica.
        link_url: link condivisione (per done).
        link_expires_at: scadenza link (datetime o None).
        user_id: utente che chiude.

    Returns:
        TransferOrder aggiornato (flush senza commit).

    Raises:
        ValueError: ordine già in stato terminale.
    """
    if order.status in _TERMINAL:
        raise ValueError(
            f"Ordine #{order.id} già chiuso (status={order.status!r}). "
            "Impossibile applicare close_order."
        )

    # Salva verifica
    order.verification = {
        "method": method,
        "ok": ok,
        "details": details or "",
    }
    order.closed_at = now_utc()
    order.closed_by_user_id = user_id

    if ok:
        order.status = "done"
        order.link_url = link_url
        order.link_expires_at = link_expires_at

        # Crea AssetMovement outgest per ogni asset
        for aid in (order.asset_ids or []):
            tracking = None
            if link_url:
                tracking = link_url[:120]

            mv = AssetMovement(
                tenant_id=order.tenant_id,
                asset_id=aid,
                movement_type=AssetMovementType.outgest,
                to_party=order.destination,
                to_contact=order.recipient_email,
                carrier=order.tool,
                tracking_number=tracking,
                contents_description=f"TransferOrder #{order.id}",
            )
            db.add(mv)

    else:
        order.status = "failed"
        # Notifica utenti con permesso edit_planning_all
        notify_permission(
            db,
            permission="edit_planning_all",
            kind="transfer_order",
            title=f"Transfer fallito: ordine #{order.id} ({order.tool} → {order.destination})",
            link="/storage",
            body=details,
            actor_user_id=user_id,
            tenant_id=order.tenant_id,
            commit=False,
        )

    db.flush()
    return order


def transition(
    db: Session,
    order: TransferOrder,
    new_status: str,
    *,
    user_id: Optional[int] = None,
) -> TransferOrder:
    """Avanza lo stato dell'ordine applicando le regole FSM F5.

    Args:
        db: sessione SQLAlchemy.
        order: istanza TransferOrder.
        new_status: stato destinazione.
        user_id: utente che effettua la transizione.

    Returns:
        TransferOrder aggiornato (flush senza commit).

    Raises:
        ValueError: transizione non permessa o stato terminale.
    """
    allowed = _TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Transizione non permessa: {order.status!r} → {new_status!r}. "
            f"Permesse: {sorted(allowed) or 'nessuna (stato terminale)'}"
        )

    if new_status in ("done", "failed", "cancelled"):
        order.closed_at = now_utc()
        order.closed_by_user_id = user_id

    order.status = new_status
    db.flush()
    return order


def apply_transfer_result(db: Session, job: AgentJob, result: dict) -> TransferOrder:
    """Gestisce l'esito positivo di un AgentJob di tipo transfer.

    Risolve l'ordine dall'agent_job_id, chiude con method="tool_rc" ok=True.
    Chiamato da process_job_result in agent_api.py.

    Args:
        db: sessione SQLAlchemy.
        job: AgentJob completato (status=done).
        result: dict ritornato dall'agent (es. {ok:True, files:N, log_tail:str}).

    Returns:
        TransferOrder aggiornato.

    Raises:
        ValueError: ordine non trovato o già chiuso.
    """
    order = _resolve_order(db, job)
    if order.status in _TERMINAL:
        raise ValueError(
            f"Ordine #{order.id} già chiuso (status={order.status!r}). "
            "apply_transfer_result ignorato."
        )
    log_tail = result.get("log_tail", "") or ""
    link_url = result.get("link_url")
    return close_order(
        db,
        order,
        ok=True,
        method="tool_rc",
        details=log_tail[:500] if log_tail else None,
        link_url=link_url,
        user_id=None,
    )


def apply_transfer_failure(db: Session, job: AgentJob, error: str) -> TransferOrder:
    """Gestisce l'esito negativo di un AgentJob di tipo transfer.

    Risolve l'ordine dall'agent_job_id, chiude con ok=False e notifica.
    Chiamato da process_job_result in agent_api.py.

    Args:
        db: sessione SQLAlchemy.
        job: AgentJob fallito.
        error: messaggio di errore dall'agent.

    Returns:
        TransferOrder aggiornato.

    Raises:
        ValueError: ordine non trovato o già chiuso.
    """
    order = _resolve_order(db, job)
    if order.status in _TERMINAL:
        raise ValueError(
            f"Ordine #{order.id} già chiuso (status={order.status!r}). "
            "apply_transfer_failure ignorato."
        )
    return close_order(
        db,
        order,
        ok=False,
        method="tool_rc",
        details=(error or "")[:500],
        user_id=None,
    )


# ── helpers interni ───────────────────────────────────────────────────

def _resolve_order(db: Session, job: AgentJob) -> TransferOrder:
    """Risolve il TransferOrder dall'agent_job_id. Solleva ValueError se non trovato."""
    row = db.execute(
        select(TransferOrder).where(TransferOrder.agent_job_id == job.id,
                                    TransferOrder.tenant_id == job.tenant_id)
    ).scalar_one_or_none()
    if row is None:
        raise ValueError(f"Nessun TransferOrder trovato per agent_job_id={job.id}.")
    return row
