"""F3.1 pipeline deliverables (v3.5.0-alpha.172.137) — snapshot specs capitolato.

`snapshot_delivery_item(db, item)` congela le specifiche tecniche risolte di un
`DeliveryItem` in un dict JSON-serializzabile, salvato in
`JobDeliverable.spec_json` al create del deliverable (decisione 4 della spec
docs/superpowers/specs/2026-05-29-deliverables-pipeline-design.md).

Scopo: il deliverable di planning è una FOTO affinabile per-file, decoupled da
modifiche successive al capitolato. La UI di planning legge/edita questo dict;
l'Asset (F3.3) ne deriva le specs "attese" per il QC.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import (
    DeliveryItem, AudioTrackSpec,
    Package, Container, VideoCodec, Resolution, FrameRate,
    AudioMixType, AudioChannelConfig, MixStandard, AudioCodec,
)
from app.services.delivery_timeline_service import effective_timeline


def _name(db: Session, model, fk: Optional[int]) -> Optional[str]:
    if not fk:
        return None
    rec = db.get(model, fk)
    return rec.name if rec else None


def _audio_track(db: Session, t: AudioTrackSpec) -> dict:
    return {
        "track_label": t.track_label,
        "channel_config": _name(db, AudioChannelConfig, t.channel_config_id),
        "mix_type": _name(db, AudioMixType, t.mix_type_id),
        "mix_standard": _name(db, MixStandard, t.mix_standard_id),
        "codec": _name(db, AudioCodec, t.audio_codec_id),
        "sample_rate_hz": t.sample_rate_hz,
        "bit_depth": t.bit_depth,
        "is_optional": bool(t.is_optional),
    }


def snapshot_delivery_item(db: Session, item: DeliveryItem) -> dict:
    """Foto JSON delle specs risolte di un DeliveryItem (decoupled dal capitolato)."""
    container = db.get(Container, item.container_id) if item.container_id else None
    tracks = sorted(item.audio_tracks or [], key=lambda t: (t.sort_order, t.id))
    return {
        "source_delivery_item_id": item.id,
        "source_delivery_template_id": item.delivery_template_id,
        "name": item.name,
        "package": _name(db, Package, item.package_id),
        "container": container.name if container else None,
        "container_extension": container.extension if container else None,
        "media_kind": container.media_kind if container else None,
        "video": {
            "codec": _name(db, VideoCodec, item.video_codec_id),
            "bit_depth": item.video_bit_depth,
            "chroma_subsampling": item.chroma_subsampling,
            "resolution": _name(db, Resolution, item.resolution_id),
            "aspect_ratio": item.aspect_ratio,
            "frame_rate": _name(db, FrameRate, item.frame_rate_id),
            "scan_type": item.scan_type,
            "color_space": item.color_space,
            "hdr_format": item.hdr_format,
        },
        "audio_tracks": [_audio_track(db, t) for t in tracks],
        "subtitle": {
            "format": item.subtitle_format,
            "languages": item.subtitle_languages or [],
        },
        "timeline": effective_timeline(db, item),
        "tc_start": item.tc_start,
        "program_start": item.program_start,
        "audio_config_code": item.audio_config_code,
        "extra_specs": item.extra_specs or {},
        "notes": item.notes,
    }
