"""v3.5.0-alpha.172.206 — Unificazione link deliverable↔asset (audit nodo B).

`DeliverableAsset` (M:N) è la FONTE DI VERITÀ. I FK singoli
`JobDeliverable.digital_asset_id` / `physical_asset_id` restano come CACHE
denormalizzata, SEMPRE risincronizzata da qui (approccio sync-as-cache): i
readers legacy (serializer, cost report, QC compare, UI) continuano a leggere i
FK senza modifiche, ma non possono più desincronizzarsi.

Regola del "primario" in cache: l'asset confermato più di recente per tipo
(digital/physical), ESCLUSO `source='qc_report'` (i file di QC non sono la
consegna). Tutti i write-site (confirm-delivery, ingest, qc-report, qc-cascade,
update_deliverable) devono passare da `link_asset` / `unlink_asset`.

Ponte AssetMembership→deliverable: `deliverables_served_by_physical` risponde a
"quali consegne serve questo nastro" unendo link diretti (pivot.physical_asset_id)
e transitivi (file sul nastro → asset digitale → pivot/Asset.job_deliverable_id).
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from app.models.models import (
    DeliverableAsset, JobDeliverable, AssetMembership, Asset, now_utc,
)

# Source che NON concorrono a definire il primario in cache.
_NON_PRIMARY_SOURCES = {"qc_report"}


def _resync_primary(db: Session, deliverable: JobDeliverable) -> None:
    """Ricalcola i FK cache (digital_asset_id/physical_asset_id) dal pivot.
    Primario = riga confermata più di recente per tipo, escluse le source
    non-primarie. NON committa."""
    rows = (
        db.query(DeliverableAsset)
        .filter(DeliverableAsset.job_deliverable_id == deliverable.id)
        .order_by(DeliverableAsset.confirmed_at.desc(), DeliverableAsset.id.desc())
        .all()
    )
    prim_digital = next(
        (r.asset_id for r in rows
         if r.asset_id is not None
         and r.superseded_at is None
         and (r.source or "") not in _NON_PRIMARY_SOURCES),
        None,
    )
    prim_physical = next(
        (r.physical_asset_id for r in rows
         if r.physical_asset_id is not None
         and r.superseded_at is None
         and (r.source or "") not in _NON_PRIMARY_SOURCES),
        None,
    )
    deliverable.digital_asset_id = prim_digital
    deliverable.physical_asset_id = prim_physical
    if prim_digital is not None or prim_physical is not None:
        if deliverable.asset_locked_at is None:
            deliverable.asset_locked_at = now_utc()
    else:
        deliverable.asset_locked_at = None


def link_asset(
    db: Session,
    deliverable: JobDeliverable,
    *,
    asset_id: Optional[int] = None,
    physical_asset_id: Optional[int] = None,
    source: str = "manual",
    user_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> DeliverableAsset:
    """Collega un asset (digital XOR physical) alla consegna: crea/aggiorna la
    riga pivot (dedup su deliverable+asset) e risincronizza i FK cache.
    NON committa (lascia al caller)."""
    has_d = asset_id is not None
    has_p = physical_asset_id is not None
    if has_d == has_p:
        raise ValueError("link_asset: esattamente uno fra asset_id e physical_asset_id")

    # Dedup: stessa consegna + stesso asset → aggiorna invece di duplicare.
    existing = (
        db.query(DeliverableAsset)
        .filter(
            DeliverableAsset.job_deliverable_id == deliverable.id,
            DeliverableAsset.asset_id == asset_id,
            DeliverableAsset.physical_asset_id == physical_asset_id,
        )
        .first()
    )
    if existing:
        existing.source = source or existing.source
        existing.confirmed_at = now_utc()
        if user_id is not None:
            existing.confirmed_by_user_id = user_id
        if notes is not None:
            existing.notes = notes
        row = existing
    else:
        row = DeliverableAsset(
            tenant_id=deliverable.tenant_id,
            job_deliverable_id=deliverable.id,
            asset_id=asset_id,
            physical_asset_id=physical_asset_id,
            source=source or "manual",
            confirmed_by_user_id=user_id,
            notes=notes,
        )
        db.add(row)
    db.flush()
    _resync_primary(db, deliverable)
    return row


def unlink_asset(
    db: Session,
    deliverable: JobDeliverable,
    *,
    asset_id: Optional[int] = None,
    physical_asset_id: Optional[int] = None,
) -> int:
    """Scollega un asset dalla consegna: elimina la/e riga/righe pivot
    corrispondenti e risincronizza i FK cache. Ritorna il numero di righe
    rimosse. NON committa."""
    q = db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == deliverable.id
    )
    if asset_id is not None:
        q = q.filter(DeliverableAsset.asset_id == asset_id)
    if physical_asset_id is not None:
        q = q.filter(DeliverableAsset.physical_asset_id == physical_asset_id)
    rows = q.all()
    for r in rows:
        db.delete(r)
    db.flush()
    _resync_primary(db, deliverable)
    return len(rows)


def list_assets(db: Session, deliverable: JobDeliverable) -> list[DeliverableAsset]:
    """Tutte le righe pivot della consegna (per UI 'asset collegati')."""
    return (
        db.query(DeliverableAsset)
        .filter(DeliverableAsset.job_deliverable_id == deliverable.id)
        .order_by(DeliverableAsset.confirmed_at.desc(), DeliverableAsset.id.desc())
        .all()
    )


def deliverables_served_by_physical(
    db: Session, physical_asset_id: int, tenant_id: int
) -> list[dict]:
    """Consegne servite da un asset fisico (nastro/disco). Unisce:
    - DIRETTE: righe pivot con physical_asset_id == nastro.
    - TRANSITIVE: file (AssetMembership attivi) sul nastro → asset digitale →
      pivot (asset_id) oppure Asset.job_deliverable_id.
    Ritorna [{deliverable, link_types:set}] deduplicato. Tenant-scoped."""
    link_types: dict[int, set] = {}

    # Dirette
    direct = (
        db.query(DeliverableAsset.job_deliverable_id)
        .filter(
            DeliverableAsset.physical_asset_id == physical_asset_id,
            DeliverableAsset.tenant_id == tenant_id,
        )
        .all()
    )
    for (did,) in direct:
        link_types.setdefault(did, set()).add("diretto")

    # Transitive: asset digitali presenti sul nastro
    asset_ids = [
        a for (a,) in db.query(AssetMembership.asset_id)
        .filter(
            AssetMembership.physical_asset_id == physical_asset_id,
            AssetMembership.tenant_id == tenant_id,
            AssetMembership.removed_at.is_(None),
            AssetMembership.asset_id.isnot(None),
        ).all()
    ]
    if asset_ids:
        for (did,) in (
            db.query(DeliverableAsset.job_deliverable_id)
            .filter(
                DeliverableAsset.asset_id.in_(asset_ids),
                DeliverableAsset.tenant_id == tenant_id,
            ).all()
        ):
            link_types.setdefault(did, set()).add("via file")
        for (did,) in (
            db.query(Asset.job_deliverable_id)
            .filter(
                Asset.id.in_(asset_ids),
                Asset.job_deliverable_id.isnot(None),
            ).all()
        ):
            if did is not None:
                link_types.setdefault(did, set()).add("via file")

    if not link_types:
        return []

    delivs = (
        db.query(JobDeliverable)
        .filter(
            JobDeliverable.id.in_(list(link_types.keys())),
            JobDeliverable.tenant_id == tenant_id,
            JobDeliverable.deleted_at.is_(None),
        )
        .all()
    )
    return [{"deliverable": d, "link_types": link_types.get(d.id, set())} for d in delivs]
