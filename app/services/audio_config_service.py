"""v3.5.0-alpha.172.127 — Materializzazione AudioConfigPreset → AudioTrackSpec.

Selezionare un preset (es. RAI 8T07) crea le tracce audio concrete sull'item
(D2). I nomi nel track_layout (channel_config/mix_type/mix_standard/codec) sono
risolti agli id taxonomy esistenti; se non risolti la traccia è creata comunque
con i campi noti + nota (fallback D5).
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import (
    AudioTrackSpec, AudioConfigPreset, DeliveryItem,
    AudioChannelConfig, AudioMixType, MixStandard, AudioCodec,
)


def _resolve_id(db: Session, model, name: Optional[str], tenant_id: int) -> Optional[int]:
    """Risolve un nome taxonomy a id (preset globali tenant_id NULL OR del tenant)."""
    if not name:
        return None
    rec = (
        db.query(model.id)
        .filter(model.name == name)
        .filter((model.tenant_id == tenant_id) | (model.tenant_id.is_(None)))
        .first()
    )
    return rec[0] if rec else None


def apply_audio_config_preset(db: Session, item: DeliveryItem,
                              preset: AudioConfigPreset) -> int:
    """Materializza le tracce del preset sull'item. Sostituisce le tracce
    esistenti derivate da un preset (ri-applicazione idempotente). Ritorna il
    numero di tracce create. NON committa (lascia al caller)."""
    # Rimuovi tracce esistenti dell'item (sostituzione in blocco, D2 nota).
    # synchronize_session="fetch": ri-sincronizza l'identity-map della sessione,
    # evitando oggetti AudioTrackSpec stale se il chiamante (router) ha già
    # caricato item.audio_tracks prima di applicare il preset.
    db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id
    ).delete(synchronize_session="fetch")

    layout = preset.track_layout or []
    created = 0
    for idx, tr in enumerate(layout):
        # Accept both name-keys (channel_config, mix_type, …) and id-keys
        # (channel_config_id, mix_type_id, …) so parser-created presets work too.
        cc_id = _resolve_id(db, AudioChannelConfig, tr.get("channel_config"), item.tenant_id) or tr.get("channel_config_id")
        mt_id = _resolve_id(db, AudioMixType, tr.get("mix_type"), item.tenant_id) or tr.get("mix_type_id")
        ms_id = _resolve_id(db, MixStandard, tr.get("mix_standard"), item.tenant_id) or tr.get("mix_standard_id")
        ac_id = _resolve_id(db, AudioCodec, tr.get("codec"), item.tenant_id) or tr.get("audio_codec_id")
        # Flag as unresolved only when a name was given AND neither name nor id-key resolved it.
        unresolved = [k for k, name_val, resolved_id, id_key in (
            ("channel_config", tr.get("channel_config"), cc_id, tr.get("channel_config_id")),
            ("mix_type",       tr.get("mix_type"),       mt_id, tr.get("mix_type_id")),
            ("mix_standard",   tr.get("mix_standard"),   ms_id, tr.get("mix_standard_id")),
            ("codec",          tr.get("codec"),          ac_id, tr.get("audio_codec_id")),
        ) if name_val and resolved_id is None and id_key is None]
        note = None
        if unresolved:
            note = "taxonomy non risolta: " + ", ".join(
                f"{k}={tr.get(k)}" for k in unresolved)
        db.add(AudioTrackSpec(
            delivery_item_id=item.id,
            sort_order=idx * 10,
            track_label=tr.get("track_label") or f"Track {idx + 1}",
            channel_config_id=cc_id,
            mix_type_id=mt_id,
            mix_standard_id=ms_id,
            audio_codec_id=ac_id,
            sample_rate_hz=tr.get("sample_rate") or tr.get("sample_rate_hz"),
            bit_depth=tr.get("bit_depth"),
            notes=note,
        ))
        created += 1

    item.audio_config_preset_id = preset.id
    item.audio_config_code = preset.code
    return created
