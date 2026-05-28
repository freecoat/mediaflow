from app.models.models import (
    DeliveryTemplate, DeliveryItem, AudioConfigPreset, AudioTrackSpec,
    AudioChannelConfig, AudioCodec,
)
from app.services.audio_config_service import apply_audio_config_preset


def _setup(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="RAI-X", name="RAI test")
    db.add(t); db.flush()
    db.add(AudioChannelConfig(tenant_id=None, name="5.1", channel_count=6))
    db.add(AudioCodec(tenant_id=None, name="PCM"))
    db.flush()
    preset = AudioConfigPreset(
        tenant_id=tenant_id, delivery_template_id=t.id, code="8T07",
        name="8T07", track_layout=[
            {"track_label": "5.1", "channel_config": "5.1", "codec": "PCM",
             "sample_rate": 48000, "bit_depth": 24},
            {"track_label": "Stereo", "channel_config": "Stereo", "codec": "PCM"},
        ])
    db.add(preset); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="HDTV")
    db.add(item); db.flush()
    return item, preset


def test_apply_preset_materializes_tracks(db, tenant_id):
    item, preset = _setup(db, tenant_id)
    n = apply_audio_config_preset(db, item, preset)
    db.flush()
    tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id).order_by(AudioTrackSpec.sort_order).all()
    assert n == 2
    assert len(tracks) == 2
    assert tracks[0].track_label == "5.1"
    assert tracks[0].channel_config_id is not None
    assert tracks[0].sample_rate_hz == 48000
    assert tracks[1].channel_config_id is None
    assert item.audio_config_preset_id == preset.id
    assert item.audio_config_code == "8T07"


def test_apply_preset_replaces_existing_derived_tracks(db, tenant_id):
    item, preset = _setup(db, tenant_id)
    apply_audio_config_preset(db, item, preset)
    db.flush()
    apply_audio_config_preset(db, item, preset)  # ri-applica
    db.flush()
    tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id).all()
    assert len(tracks) == 2  # non duplica
