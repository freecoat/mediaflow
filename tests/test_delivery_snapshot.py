"""F3.1 pipeline deliverables — snapshot specs DeliveryItem → JobDeliverable.spec_json.

`snapshot_delivery_item(db, item)` congela le specifiche tecniche risolte di un
DeliveryItem (nomi taxonomy, tracce audio, timeline/TC ereditati, sottotitoli)
in un dict strutturato. Salvato in `JobDeliverable.spec_json` al create, così il
deliverable è decoupled da edit successivi al capitolato (decisione 4 della spec).
"""
import pytest
from app.models.models import (
    Tenant, DeliveryTemplate, DeliveryItem, AudioTrackSpec,
    Container, VideoCodec, Resolution, AudioMixType, AudioChannelConfig,
)
from app.services.delivery_snapshot import snapshot_delivery_item


@pytest.fixture
def seeded(db, tenant_id):
    db.add(Tenant(id=tenant_id, name="T", slug="t"))
    db.add(Container(id=1, tenant_id=tenant_id, name="QuickTime", media_kind="mixed", extension=".mov"))
    db.add(Container(id=2, tenant_id=tenant_id, name="WAV", media_kind="audio"))
    db.add(VideoCodec(id=1, tenant_id=tenant_id, name="Apple ProRes 422 HQ"))
    db.add(Resolution(id=1, tenant_id=tenant_id, name="HD 1080p", width=1920, height=1080))
    db.add(AudioMixType(id=1, tenant_id=tenant_id, name="Full Mix (Final Mix)"))
    db.add(AudioChannelConfig(id=1, tenant_id=tenant_id, name="5.1 SMPTE", channel_count=6))
    db.add(DeliveryTemplate(id=1, tenant_id=tenant_id, code="T1", name="Tmpl",
                            default_tc_start="00:59:59:00"))
    db.commit()
    return db


def _mk_item(db, tenant_id, **kw):
    it = DeliveryItem(tenant_id=tenant_id, delivery_template_id=1,
                      name=kw.pop("name", "x"), **kw)
    db.add(it); db.commit()
    return it


def test_snapshot_video_resolves_taxonomy_names(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="Master ProRes",
                  container_id=1, video_codec_id=1, resolution_id=1,
                  video_bit_depth=10, hdr_format="HDR10", aspect_ratio="16:9",
                  color_space="Rec.2020 PQ")
    snap = snapshot_delivery_item(seeded, it)
    assert snap["source_delivery_item_id"] == it.id
    assert snap["name"] == "Master ProRes"
    assert snap["container"] == "QuickTime"
    assert snap["video"]["codec"] == "Apple ProRes 422 HQ"
    assert snap["video"]["resolution"] == "HD 1080p"
    assert snap["video"]["bit_depth"] == 10
    assert snap["video"]["hdr_format"] == "HDR10"
    assert snap["video"]["color_space"] == "Rec.2020 PQ"


def test_snapshot_audio_tracks(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="Mix", container_id=2)
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0, track_label="Mix 5.1",
                              mix_type_id=1, channel_config_id=1, sample_rate_hz=48000,
                              bit_depth=24, is_optional=False))
    seeded.commit()
    snap = snapshot_delivery_item(seeded, it)
    assert len(snap["audio_tracks"]) == 1
    t = snap["audio_tracks"][0]
    assert t["track_label"] == "Mix 5.1"
    assert t["mix_type"] == "Full Mix (Final Mix)"
    assert t["channel_config"] == "5.1 SMPTE"
    assert t["sample_rate_hz"] == 48000
    assert t["bit_depth"] == 24
    assert t["is_optional"] is False


def test_snapshot_timeline_inherited_from_template(seeded, tenant_id):
    """tc_start non sull'item → ereditato dal template (effective_timeline)."""
    it = _mk_item(seeded, tenant_id, name="x", container_id=1, video_codec_id=1, resolution_id=1)
    snap = snapshot_delivery_item(seeded, it)
    assert snap["timeline"]["tc_start"] == "00:59:59:00"
    assert snap["timeline"]["tc_start_inherited"] is True


def test_snapshot_subtitle_and_extra(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="x", container_id=1, video_codec_id=1, resolution_id=1,
                  subtitle_format="TTML IMSC 1.1", subtitle_languages=["it", "en"],
                  extra_specs={"naming": "X_Y_Z"}, notes="Frame.io upload")
    snap = snapshot_delivery_item(seeded, it)
    assert snap["subtitle"]["format"] == "TTML IMSC 1.1"
    assert snap["subtitle"]["languages"] == ["it", "en"]
    assert snap["extra_specs"] == {"naming": "X_Y_Z"}
    assert snap["notes"] == "Frame.io upload"


def test_snapshot_is_plain_json(seeded, tenant_id):
    """Lo snapshot deve essere JSON-serializzabile (niente oggetti ORM)."""
    import json
    it = _mk_item(seeded, tenant_id, name="x", container_id=1, video_codec_id=1, resolution_id=1)
    snap = snapshot_delivery_item(seeded, it)
    json.dumps(snap)  # non deve sollevare
