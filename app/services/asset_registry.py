"""F1 (spec 2026-06-10) — Registro asset metadata-only.

Crea proposte Asset dai risultati probe dell'agent ("agent propone,
operatore dispone"), dedup per checksum+volume, guard anti-upload
contenuti media sul server.
"""
from __future__ import annotations
from pathlib import PurePosixPath
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    Asset, AssetType, AssetStatus, AssetContentState, AssetProposedState,
)

_CONTENT_EXT = {
    ".mov", ".mxf", ".mp4", ".mkv", ".avi", ".webm",
    ".wav", ".aif", ".aiff", ".flac", ".bwf",
    ".dpx", ".exr", ".ari", ".r3d", ".braw", ".dng",
}


def is_content_file(filename: str, mime_type: Optional[str]) -> bool:
    """True = contenuto media (vietato upload server, solo registrazione agent).
    Documenti business (pdf, immagini singole, office) restano uploadabili."""
    if mime_type and (mime_type.startswith("video/") or mime_type.startswith("audio/")):
        return True
    ext = PurePosixPath(filename.lower().replace("\\", "/")).suffix
    return ext in _CONTENT_EXT


def _asset_type_from_mime(mime: Optional[str]) -> AssetType:
    if not mime:
        return AssetType.other
    if mime.startswith("video/"):
        return AssetType.video
    if mime.startswith("audio/"):
        return AssetType.audio
    if mime.startswith("image/"):
        return AssetType.image
    return AssetType.other


def create_proposal_from_probe(db: Session, *, tenant_id: int, volume_id: int,
                               probe: dict, user_id: int,
                               registered_via: str = "manual_path") -> Asset:
    """Crea Asset `pending_review` dal payload probe agent.
    Dedup: stesso checksum_xxhash sullo stesso volume → ritorna l'esistente."""
    checksum = probe.get("checksum_xxhash")
    if checksum:
        existing = db.execute(
            select(Asset).where(Asset.tenant_id == tenant_id,
                                Asset.storage_volume_id == volume_id,
                                Asset.checksum_xxhash == checksum)
        ).scalar_one_or_none()
        if existing is not None:
            return existing
    rel_path = (probe.get("rel_path") or "").lstrip("/")
    name = PurePosixPath(rel_path.replace("\\", "/")).name or rel_path
    mime = probe.get("mime_type")
    asset = Asset(
        tenant_id=tenant_id,
        filename=name, original_name=name,
        file_path=f"agent://{volume_id}/{rel_path}",
        storage_volume_id=volume_id, rel_path=rel_path,
        asset_type=_asset_type_from_mime(mime),
        mime_type=mime or "application/octet-stream",
        file_size=int(probe.get("file_size") or 0),
        uploaded_by=user_id,
        status=AssetStatus.uploaded,
        content_state=AssetContentState.online,
        proposed_state=AssetProposedState.pending_review,
        checksum_xxhash=checksum,
        registered_via=registered_via,
        tech_specs_json=probe.get("tech_specs"),
        tech_specs_extractor="agent-ffprobe",
    )
    db.add(asset)
    db.flush()
    return asset


def confirm_proposal(db: Session, asset: Asset, *, user_id: int) -> Asset:
    asset.proposed_state = AssetProposedState.confirmed
    db.flush()
    return asset


def discard_proposal(db: Session, asset: Asset) -> Asset:
    asset.proposed_state = AssetProposedState.discarded
    db.flush()
    return asset
