"""F3 (spec 2026-06-11) — Preview QC: enqueue job agent + esiti.

Il server decide la destinazione upload nel payload del job:
- S3 configurato via env (PREVIEW_S3_BUCKET, PREVIEW_S3_REGION,
  PREVIEW_S3_ACCESS_KEY, PREVIEW_S3_SECRET_KEY, opz. PREVIEW_S3_ENDPOINT)
  → presigned PUT, l'agent carica diretto, il server non vede i byte.
- Altrimenti → l'agent streama il file a PUT /agent-api/jobs/{id}/preview-upload.

Importazione boto3 LAZY (dentro le funzioni): nessun hard-dependency runtime
su un pacchetto opzionale.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    AgentJob, AgentJobStatus, AgentJobType, Asset,
)
from app.services.agent_queue import enqueue_job
from app.services.clock import now_utc

# Directory locale dove l'agent carica i file proxy in modalità "server".
# I test monkeypatchano questa costante a livello di modulo.
PREVIEW_DIR: Path = Path(os.environ.get("PREVIEW_DIR", "data/previews"))


# ── Configurazione S3 ────────────────────────────────────────────────────────

def s3_preview_config() -> Optional[dict]:
    """Legge configurazione S3 da variabili d'ambiente.

    Ritorna None se manca PREVIEW_S3_BUCKET (modalità server locale).
    Campi: bucket, region, access_key, secret_key, endpoint (opzionale).
    """
    bucket = os.environ.get("PREVIEW_S3_BUCKET")
    if not bucket:
        return None
    return {
        "bucket": bucket,
        "region": os.environ.get("PREVIEW_S3_REGION", "eu-west-1"),
        "access_key": os.environ.get("PREVIEW_S3_ACCESS_KEY", ""),
        "secret_key": os.environ.get("PREVIEW_S3_SECRET_KEY", ""),
        "endpoint": os.environ.get("PREVIEW_S3_ENDPOINT"),
    }


def _s3_client(cfg: dict):
    """Crea client boto3 S3 con la configurazione fornita (import lazy)."""
    import boto3  # noqa: PLC0415 — import intenzionalmente lazy
    kwargs: dict = {
        "aws_access_key_id": cfg["access_key"],
        "aws_secret_access_key": cfg["secret_key"],
        "region_name": cfg["region"],
    }
    if cfg.get("endpoint"):
        kwargs["endpoint_url"] = cfg["endpoint"]
    return boto3.client("s3", **kwargs)


def s3_key_for(asset: Asset) -> str:
    """Chiave S3 per il proxy preview di un asset: previews/{tenant_id}/{id}.mp4."""
    return f"previews/{asset.tenant_id}/{asset.id}.mp4"


def local_path_for(asset: Asset) -> Path:
    """Percorso locale atteso per il proxy preview.

    Costruito da PREVIEW_DIR (monkeypatchabile nei test).
    """
    return PREVIEW_DIR / str(asset.tenant_id) / f"{asset.id}.mp4"


# ── Job pending helper ───────────────────────────────────────────────────────

def _pending_preview_job(db: Session, asset: Asset) -> Optional[AgentJob]:
    """Trova job preview ancora attivo (queued/claimed/running) per questo asset."""
    pending_statuses = [
        AgentJobStatus.queued,
        AgentJobStatus.claimed,
        AgentJobStatus.running,
    ]
    rows = db.execute(
        select(AgentJob).where(
            AgentJob.tenant_id == asset.tenant_id,
            AgentJob.type == AgentJobType.preview,
            AgentJob.status.in_(pending_statuses),
            AgentJob.asset_id == asset.id,
        )
    ).scalars().all()
    # Filtra per payload.asset_id per sicurezza aggiuntiva
    for job in rows:
        payload = job.payload or {}
        if payload.get("asset_id") == asset.id:
            return job
    return None


# ── Enqueue ──────────────────────────────────────────────────────────────────

def enqueue_preview(
    db: Session,
    asset: Asset,
    *,
    requested_by_user_id: Optional[int] = None,
) -> AgentJob:
    """Accoda un job di generazione preview per l'asset.

    Idempotente: se esiste già un job queued/claimed/running per lo stesso
    asset, lo ritorna senza creare un duplicato.

    Raise:
        ValueError: se asset manca di storage_volume_id o rel_path.
    """
    # Validazione precondizioni
    if not asset.storage_volume_id:
        raise ValueError(
            f"Asset {asset.id}: storage_volume_id mancante, impossibile accodare preview"
        )
    if not asset.rel_path:
        raise ValueError(
            f"Asset {asset.id}: rel_path mancante, impossibile accodare preview"
        )

    # Idempotenza: ritorna pending esistente
    pending = _pending_preview_job(db, asset)
    if pending is not None:
        return pending

    # Determina modalità upload
    upload: dict
    try:
        cfg = s3_preview_config()
        if cfg is not None:
            client = _s3_client(cfg)
            key = s3_key_for(asset)
            put_url = client.generate_presigned_url(
                "put_object",
                Params={"Bucket": cfg["bucket"], "Key": key,
                        "ContentType": "video/mp4"},
                ExpiresIn=3600,
            )
            upload = {"mode": "s3", "put_url": put_url, "key": key}
        else:
            upload = {"mode": "server"}
    except ImportError:
        # boto3 non installato → degrada a server
        upload = {"mode": "server"}

    # Nome tenant per log dell'agent
    tenant_name = "Claqo"
    try:
        if asset.tenant and asset.tenant.name:
            tenant_name = asset.tenant.name
    except Exception:  # noqa: BLE001 — relationship non caricata
        pass

    payload = {
        "volume_id": asset.storage_volume_id,
        "rel_path": asset.rel_path,
        "asset_id": asset.id,
        "tenant_name": tenant_name,
        "upload": upload,
    }

    job = enqueue_job(
        db,
        tenant_id=asset.tenant_id,
        type=AgentJobType.preview,
        payload=payload,
        requested_by_user_id=requested_by_user_id,
        asset_id=asset.id,
    )

    # Aggiorna stato asset
    asset.preview_status = "queued"
    asset.preview_error = None
    db.flush()

    return job


# ── Esiti job ────────────────────────────────────────────────────────────────

def apply_preview_result(
    db: Session,
    job: AgentJob,
    result: dict,
) -> Optional[Asset]:
    """Applica il risultato positivo del job preview all'asset.

    Atteso in result:
        uploaded   : "server" | "s3"
        preview_path: percorso locale (solo mode server)
        start_tc   : timecode iniziale es. "01:00:00:00"
        fps        : float
        duration_sec: float
        burned_tc  : bool — il proxy ha il TC bruciato

    In caso di file locale mancante imposta status=failed.
    """
    payload = job.payload or {}
    asset_id = payload.get("asset_id")
    if asset_id is None:
        return None

    asset = db.get(Asset, asset_id)
    if asset is None or asset.tenant_id != job.tenant_id:
        return None

    uploaded = result.get("uploaded", "server")

    if uploaded == "s3":
        # Il file è già su S3; la chiave è nel payload del job
        upload_info = payload.get("upload", {})
        asset.preview_storage = "s3"
        asset.preview_path = upload_info.get("key") or result.get("preview_path")
        _mark_ready(asset, result)
    else:
        # Modalità server: verifica che il file esista localmente
        preview_path_str = result.get("preview_path")
        if not preview_path_str or not Path(preview_path_str).exists():
            asset.preview_status = "failed"
            asset.preview_error = (
                f"File preview non trovato: {preview_path_str!r}"
            )
            db.flush()
            return asset

        asset.preview_storage = "local"
        asset.preview_path = preview_path_str
        _mark_ready(asset, result)

    db.flush()
    return asset


def _mark_ready(asset: Asset, result: dict) -> None:
    """Imposta preview_status=ready e popola preview_meta dal result."""
    asset.preview_status = "ready"
    asset.preview_error = None
    asset.preview_generated_at = now_utc()
    asset.preview_meta = {
        "start_tc": result.get("start_tc"),
        "fps": result.get("fps"),
        "duration_sec": result.get("duration_sec"),
        "burned_tc": result.get("burned_tc", False),
    }


def apply_preview_failure(
    db: Session,
    job: AgentJob,
    error: str,
) -> Optional[Asset]:
    """Applica un esito negativo del job preview all'asset.

    Imposta preview_status=failed e preview_error (troncato a 2000 caratteri).
    """
    payload = job.payload or {}
    asset_id = payload.get("asset_id")
    if asset_id is None:
        return None

    asset = db.get(Asset, asset_id)
    if asset is None or asset.tenant_id != job.tenant_id:
        return None

    asset.preview_status = "failed"
    asset.preview_error = (error or "")[:2000]
    db.flush()
    return asset


# ── URL firmato per accesso S3 ───────────────────────────────────────────────

def presigned_get_url(asset: Asset, *, expires: int = 900) -> str:
    """Genera URL presigned GET per scaricare/streamare il proxy S3.

    Raise:
        ValueError: se S3 non è configurato.
    """
    cfg = s3_preview_config()
    if cfg is None:
        raise ValueError(
            "PREVIEW_S3_BUCKET non configurato: presigned URL non disponibile"
        )
    client = _s3_client(cfg)
    key = asset.preview_path or s3_key_for(asset)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": cfg["bucket"], "Key": key},
        ExpiresIn=expires,
    )
