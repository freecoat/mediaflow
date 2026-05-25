"""Cascade su QC reject di JobDeliverable (Bundle I — v3.5.0-alpha.172.89).

Quando un deliverable transita a (status=qc, qc_substatus=rejected):
1. Main status torna a `planned`, qc_substatus a None
2. Asset principali linkati via DeliverableAsset (source != 'qc_report') ricevono
   status=`rejected`
3. Spawn placeholder Asset(status=planned, parent_asset_id=originale, file_path
   vuoto) linkato al deliverable con DeliverableAsset(source='manual')
4. Notifica in-app a utenti con permesso 'view_finance' (NotificationKind
   deliverable_qc_rejected)

Idempotenza: chiamare due volte non duplica placeholder (skip se ne esiste già
uno post-reject con parent_asset_id su asset rejected linkato a questo deliv).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    JobDeliverable, Asset, DeliverableAsset,
    DeliverableStatus, AssetStatus,
)


def cascade_qc_reject(
    db: Session,
    deliverable: JobDeliverable,
    *,
    actor_user_id: Optional[int] = None,
    reason: Optional[str] = None,
) -> dict:
    """Esegue la cascade. Caller deve aver gia' settato qc_substatus=rejected
    PRIMA di invocare. Questa funzione resetta status main + applica cascade.

    Return: dict con conteggi {assets_rejected, placeholders_spawned, notified}.
    """
    counters = {"assets_rejected": 0, "placeholders_spawned": 0, "notified": 0}

    # 1. Reset main status + substatus
    deliverable.status = DeliverableStatus.planned
    deliverable.qc_substatus = None

    # 2. Asset principali (non report QC) → status='rejected'
    asset_links = db.query(DeliverableAsset).filter(
        DeliverableAsset.job_deliverable_id == deliverable.id,
        DeliverableAsset.asset_id.isnot(None),
        DeliverableAsset.source != "qc_report",
    ).all()

    rejected_originals = []
    for link in asset_links:
        asset = db.query(Asset).filter(Asset.id == link.asset_id).first()
        if not asset:
            continue
        if asset.status != AssetStatus.rejected:
            asset.status = AssetStatus.rejected
            counters["assets_rejected"] += 1
            rejected_originals.append(asset)

    # 3. Spawn placeholder per ogni asset rejected (skip se gia' esiste)
    for original in rejected_originals:
        existing_placeholder = db.query(Asset).filter(
            Asset.parent_asset_id == original.id,
            Asset.status == AssetStatus.planned,
        ).first()
        if existing_placeholder:
            continue
        placeholder = Asset(
            tenant_id=original.tenant_id,
            filename=f"{original.filename} (re-run QC)"[:255],
            original_name=f"{original.original_name} (re-run QC)"[:255],
            file_path="",  # placeholder vuoto
            asset_type=original.asset_type,
            mime_type=original.mime_type,
            file_size=0,
            description=f"Placeholder dopo QC reject del file originale (id={original.id}). "
                        f"Caricare nuovo file finalizzato.",
            job_id=original.job_id,
            project_id=original.project_id,
            uploaded_by=actor_user_id or original.uploaded_by,
            version=(original.version or 1) + 1,
            parent_asset_id=original.id,
            status=AssetStatus.planned,
        )
        db.add(placeholder)
        db.flush()
        # Link al deliverable via DeliverableAsset (source='manual', placeholder)
        link = DeliverableAsset(
            job_deliverable_id=deliverable.id,
            asset_id=placeholder.id,
            source="manual",
            confirmed_by_user_id=actor_user_id,
            notes=f"Spawn auto post QC reject originale id={original.id}",
        )
        db.add(link)
        counters["placeholders_spawned"] += 1

    # 4. Notifica in-app (non bloccante)
    try:
        from app.services.notifications import notify_permission
        body = (
            f"Deliverable '{deliverable.name}' rifiutato in QC. "
            f"{counters['assets_rejected']} asset principali marcati rejected, "
            f"{counters['placeholders_spawned']} placeholder creati per re-upload."
        )
        if reason:
            body += f"\n\nNota QC: {reason}"
        notifs = notify_permission(
            db,
            permission="view_finance",
            kind="deliverable_qc_rejected",
            severity="action_required",
            title=f"QC rifiutato — {deliverable.name[:60]}",
            body=body,
            link=f"/cost-report#job-{deliverable.job_id}",
            payload={
                "deliverable_id": deliverable.id,
                "job_id": deliverable.job_id,
                "assets_rejected": counters["assets_rejected"],
                "placeholders_spawned": counters["placeholders_spawned"],
            },
            actor_user_id=actor_user_id,
            tenant_id=deliverable.tenant_id,
            commit=False,  # commit gestito dal caller (router endpoint)
        )
        counters["notified"] = len(notifs)
    except Exception as e:
        print(f"[qc_cascade] notify failed (non bloccante): {e}")

    return counters
