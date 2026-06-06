"""v3.5.0-alpha.172.202 — Audio override per-deliverable.

Verifica che apply_audio_config_preset sia generalizzato a JobDeliverable
(oltre a DeliveryItem) e che le tracce per-consegna siano isolate da quelle
del capitolato (DeliveryItem condiviso).
"""
from app.models.models import (
    DeliveryTemplate, DeliveryItem, JobDeliverable, AudioConfigPreset,
    AudioTrackSpec, AudioChannelConfig, AudioCodec,
)
from app.services.audio_config_service import apply_audio_config_preset


def _setup(db, tenant_id):
    t = DeliveryTemplate(tenant_id=tenant_id, code="SKY-X", name="Sky test", broadcaster="SKY")
    db.add(t); db.flush()
    db.add(AudioChannelConfig(tenant_id=None, name="5.1", channel_count=6))
    db.add(AudioCodec(tenant_id=None, name="PCM"))
    db.flush()
    preset = AudioConfigPreset(
        tenant_id=tenant_id, delivery_template_id=t.id, code="8T07", name="8T07",
        track_layout=[
            {"track_label": "5.1", "channel_config": "5.1", "codec": "PCM",
             "sample_rate": 48000, "bit_depth": 24},
            {"track_label": "Stereo", "channel_config": "Stereo", "codec": "PCM"},
        ])
    db.add(preset); db.flush()
    item = DeliveryItem(tenant_id=tenant_id, delivery_template_id=t.id, name="HDTV")
    db.add(item); db.flush()
    deliverable = JobDeliverable(tenant_id=tenant_id, job_id=1, name="Full Mix 5.1")
    db.add(deliverable); db.flush()
    return t, preset, item, deliverable


def test_apply_preset_on_deliverable_materializes_own_tracks(db, tenant_id):
    _t, preset, _item, d = _setup(db, tenant_id)
    n = apply_audio_config_preset(db, d, preset)
    db.flush()
    tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.job_deliverable_id == d.id
    ).order_by(AudioTrackSpec.sort_order).all()
    assert n == 2
    assert len(tracks) == 2
    # tracce taggate sul deliverable, non sull'item
    assert all(tr.job_deliverable_id == d.id for tr in tracks)
    assert all(tr.delivery_item_id is None for tr in tracks)
    assert tracks[0].track_label == "5.1"
    assert tracks[0].sample_rate_hz == 48000
    assert d.audio_config_preset_id == preset.id
    assert d.audio_config_code == "8T07"


def test_deliverable_preset_isolated_from_item(db, tenant_id):
    """Applicare il preset alla consegna NON tocca le tracce del DeliveryItem
    (capitolato condiviso) e viceversa."""
    _t, preset, item, d = _setup(db, tenant_id)
    apply_audio_config_preset(db, item, preset); db.flush()
    apply_audio_config_preset(db, d, preset); db.flush()
    item_tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id).all()
    deliv_tracks = db.query(AudioTrackSpec).filter(
        AudioTrackSpec.job_deliverable_id == d.id).all()
    assert len(item_tracks) == 2
    assert len(deliv_tracks) == 2
    # nessuna traccia ha entrambi i parent (invariante esattamente-uno)
    for tr in item_tracks + deliv_tracks:
        assert (tr.delivery_item_id is None) != (tr.job_deliverable_id is None)


def test_reapply_replaces_only_deliverable_tracks(db, tenant_id):
    _t, preset, item, d = _setup(db, tenant_id)
    apply_audio_config_preset(db, item, preset); db.flush()
    apply_audio_config_preset(db, d, preset); db.flush()
    apply_audio_config_preset(db, d, preset); db.flush()  # ri-applica al deliverable
    assert db.query(AudioTrackSpec).filter(
        AudioTrackSpec.job_deliverable_id == d.id).count() == 2  # no duplicati
    assert db.query(AudioTrackSpec).filter(
        AudioTrackSpec.delivery_item_id == item.id).count() == 2  # item intatto


def test_audiotrack_nullable_item_with_deliverable_only(db, tenant_id):
    """Una AudioTrackSpec può esistere con solo job_deliverable_id (delivery_item_id
    NULL) — il NOT NULL storico è stato rilassato."""
    d = JobDeliverable(tenant_id=tenant_id, job_id=1, name="X")
    db.add(d); db.flush()
    tr = AudioTrackSpec(job_deliverable_id=d.id, track_label="Mix", sort_order=0)
    db.add(tr); db.flush()
    assert tr.id is not None
    assert tr.delivery_item_id is None
    assert tr.job_deliverable_id == d.id
