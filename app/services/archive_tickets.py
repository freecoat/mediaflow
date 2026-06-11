"""app/services/archive_tickets.py
F4 (spec 2026-06-11) — Ticket assistito archivio/restore LTO.

YoYotta resta manuale: questo service traccia richiesta → lavorazione → esito
e aggiorna content_state dell'Asset al completamento.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import (
    ArchiveTicket,
    Asset,
    AssetContentState,
    AssetMembership,
    JobDeliverable,
    PhysicalAsset,
    PhysicalAssetKind,
)
from app.services.clock import now_utc
from app.services.notifications import notify, notify_permission

# Transizioni legali status: {corrente: set dei nuovi stati ammessi}
_TRANSITIONS: dict[str, set[str]] = {
    "requested":   {"in_progress", "done", "cancelled"},
    "in_progress": {"done", "cancelled"},
    "done":        set(),
    "cancelled":   set(),
}


def _label(ticket: ArchiveTicket, db: Session) -> str:
    """Titolo leggibile per notifica: preferisce filename asset, poi nome deliverable."""
    if ticket.asset_id:
        asset = db.get(Asset, ticket.asset_id)
        if asset:
            return asset.original_name or asset.filename
    if ticket.job_deliverable_id:
        d = db.get(JobDeliverable, ticket.job_deliverable_id)
        if d:
            return d.name or f"Deliverable #{d.id}"
    return f"Ticket #{ticket.id}"


def _active_lto_membership(db: Session, asset_id: int,
                           tenant_id: int = 1) -> Optional[AssetMembership]:
    """Restituisce la membership ATTIVA più recente su un PhysicalAsset kind=lto."""
    rows = (
        db.query(AssetMembership, PhysicalAsset)
        .join(PhysicalAsset, PhysicalAsset.id == AssetMembership.physical_asset_id)
        .filter(
            AssetMembership.asset_id == asset_id,
            AssetMembership.tenant_id == tenant_id,
            PhysicalAsset.tenant_id == tenant_id,
            AssetMembership.removed_at.is_(None),
            PhysicalAsset.kind == PhysicalAssetKind.lto,
        )
        .order_by(AssetMembership.added_at.desc())
        .first()
    )
    if rows is None:
        return None
    membership, _ = rows
    return membership


def create_ticket(
    db: Session,
    *,
    kind: str,
    asset: Optional[Asset] = None,
    deliverable: Optional[JobDeliverable] = None,
    note: Optional[str] = None,
    user_id: Optional[int] = None,
    tenant_id: int = 1,
) -> ArchiveTicket:
    """Crea un ticket archivio/restore.

    Raises:
        ValueError: kind non valido, nessun target (asset o deliverable).
    """
    if kind not in ("archive", "restore"):
        raise ValueError(f"kind deve essere 'archive' o 'restore', ricevuto: {kind!r}")
    if asset is None and deliverable is None:
        raise ValueError("Almeno uno tra asset e deliverable deve essere fornito.")

    ticket = ArchiveTicket(
        tenant_id=tenant_id,
        kind=kind,
        asset_id=asset.id if asset else None,
        job_deliverable_id=deliverable.id if deliverable else None,
        note=note,
        requested_by_user_id=user_id,
    )

    # restore con asset: suggerisci il tape dalla membership attiva più recente
    if kind == "restore" and asset is not None:
        m = _active_lto_membership(db, asset.id, tenant_id=tenant_id)
        ticket.physical_asset_id = m.physical_asset_id if m else None

    db.add(ticket)
    db.flush()

    # Determina label DOPO flush (ticket.id è disponibile)
    label = _label(ticket, db)
    title = f"Ticket {kind}: {label}"

    notify_permission(
        db,
        permission="edit_planning_all",
        kind="archive_ticket",
        title=title,
        link="/storage",
        body=note,
        actor_user_id=user_id,
        tenant_id=tenant_id,
        commit=False,
    )

    return ticket


def transition(
    db: Session,
    ticket: ArchiveTicket,
    new_status: str,
    *,
    user_id: Optional[int] = None,
) -> ArchiveTicket:
    """Avanza lo stato del ticket applicando le regole di transizione F4.

    Raises:
        ValueError: transizione non permessa, o invariante di business violata.

    Note:
        Non fa commit — il caller decide quando flushere/committare.
    """
    allowed = _TRANSITIONS.get(ticket.status, set())
    if new_status not in allowed:
        raise ValueError(
            f"Transizione non permessa: {ticket.status!r} → {new_status!r}. "
            f"Permesse: {sorted(allowed) or 'nessuna (stato terminale)'}"
        )

    if new_status == "in_progress":
        ticket.assigned_to_user_id = user_id

    elif new_status == "done":
        ticket.closed_at = now_utc()
        ticket.closed_by_user_id = user_id

        if ticket.kind == "restore":
            # Aggiorna content_state dell'asset → online
            if ticket.asset_id:
                asset = db.get(Asset, ticket.asset_id)
                if asset:
                    asset.content_state = AssetContentState.online

            # Notifica il richiedente
            if ticket.requested_by_user_id:
                label = _label(ticket, db)
                notify(
                    db,
                    user_ids=[ticket.requested_by_user_id],
                    kind="archive_ticket",
                    title=f"Restore completato: {label}",
                    link="/storage",
                    actor_user_id=user_id,
                    tenant_id=ticket.tenant_id,
                    commit=False,
                )

        elif ticket.kind == "archive":
            if ticket.asset_id:
                # Verifica che esista almeno una membership attiva su LTO
                m = _active_lto_membership(db, ticket.asset_id,
                                           tenant_id=ticket.tenant_id)
                if m is None:
                    raise ValueError(
                        "Ingest prima il catalogo del tape: nessuna membership attiva "
                        f"su LTO per asset #{ticket.asset_id}."
                    )
                asset = db.get(Asset, ticket.asset_id)
                if asset:
                    asset.content_state = AssetContentState.archived_only
            else:
                # Solo deliverable: nessun asset → membership LTO non verificabile.
                raise ValueError(
                    "Archive ticket su deliverable senza asset digitale: collega "
                    "prima l'asset (ingest catalogo) per chiudere il ticket."
                )

    elif new_status == "cancelled":
        ticket.closed_at = now_utc()
        ticket.closed_by_user_id = user_id

    ticket.status = new_status
    db.flush()
    return ticket
