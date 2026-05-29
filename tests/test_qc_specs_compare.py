"""F3.3 pipeline deliverables — confronto QC specs attese vs reali.

Lazy bridge (decisione F3.3): nessun Asset placeholder. Le specs attese sono
derivate live dal DeliveryItem collegato; le reali da `asset.tech_specs_json`
(shape ffprobe). `compare_to_actual()` produce un report per-campo
(match/mismatch/unknown) tollerante alle differenze di vocabolario codec.
"""
import pytest
from app.models.models import (
    Tenant, DeliveryTemplate, DeliveryItem, AudioTrackSpec,
    Container, VideoCodec, Resolution, AudioMixType, AudioChannelConfig,
)
from app.services.qc_specs_compare import build_expected, compare_to_actual


@pytest.fixture
def seeded(db, tenant_id):
    db.add(Tenant(id=tenant_id, name="T", slug="t"))
    db.add(Container(id=1, tenant_id=tenant_id, name="QuickTime", media_kind="mixed"))
    db.add(VideoCodec(id=1, tenant_id=tenant_id, name="Apple ProRes 422 HQ", family="ProRes"))
    db.add(Resolution(id=1, tenant_id=tenant_id, name="HD 1080p", width=1920, height=1080))
    db.add(AudioChannelConfig(id=1, tenant_id=tenant_id, name="5.1 SMPTE", channel_count=6))
    db.add(AudioChannelConfig(id=2, tenant_id=tenant_id, name="Stereo 2.0", channel_count=2))
    db.add(AudioMixType(id=1, tenant_id=tenant_id, name="Full Mix"))
    db.add(DeliveryTemplate(id=1, tenant_id=tenant_id, code="T1", name="Tmpl"))
    db.commit()
    return db


def _mk_item(db, tenant_id, **kw):
    it = DeliveryItem(tenant_id=tenant_id, delivery_template_id=1, name=kw.pop("name", "x"), **kw)
    db.add(it); db.commit()
    return it


def test_build_expected_video_and_audio(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, container_id=1, video_codec_id=1, resolution_id=1, hdr_format="HDR10")
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0, track_label="Mix",
                              mix_type_id=1, channel_config_id=1))
    seeded.commit()
    exp = build_expected(seeded, it)
    assert exp["video"]["width"] == 1920
    assert exp["video"]["height"] == 1080
    assert exp["video"]["codec_family"] == "ProRes"
    assert exp["video"]["hdr_format"] == "HDR10"
    assert exp["audio_channels"] == [6]


def test_compare_all_match(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, container_id=1, video_codec_id=1, resolution_id=1)
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0, track_label="Mix",
                              mix_type_id=1, channel_config_id=1))
    seeded.commit()
    exp = build_expected(seeded, it)
    actual = {"video": {"width": 1920, "height": 1080, "codec": "prores", "framerate": 25.0},
              "audio": [{"codec": "pcm_s24le", "channels": 6}]}
    rep = compare_to_actual(exp, actual)
    assert rep["ok"] is True
    assert rep["summary"]["mismatch"] == 0
    verdicts = {f["field"]: f["verdict"] for f in rep["fields"]}
    assert verdicts["resolution"] == "match"
    assert verdicts["video_codec"] == "match"   # "ProRes" ~ "prores"
    assert verdicts["audio_channels"] == "match"


def test_compare_resolution_mismatch(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, container_id=1, video_codec_id=1, resolution_id=1)
    seeded.commit()
    exp = build_expected(seeded, it)
    actual = {"video": {"width": 1280, "height": 720, "codec": "prores"}, "audio": []}
    rep = compare_to_actual(exp, actual)
    assert rep["ok"] is False
    verdicts = {f["field"]: f["verdict"] for f in rep["fields"]}
    assert verdicts["resolution"] == "mismatch"
    res_field = next(f for f in rep["fields"] if f["field"] == "resolution")
    assert res_field["expected"] == "1920x1080"
    assert res_field["actual"] == "1280x720"


def test_compare_audio_channel_mismatch(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, container_id=1, video_codec_id=1, resolution_id=1)
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0, track_label="Mix",
                              mix_type_id=1, channel_config_id=1))  # expects 6
    seeded.commit()
    exp = build_expected(seeded, it)
    actual = {"video": {"width": 1920, "height": 1080, "codec": "prores"},
              "audio": [{"codec": "pcm", "channels": 2}]}  # got stereo
    rep = compare_to_actual(exp, actual)
    verdicts = {f["field"]: f["verdict"] for f in rep["fields"]}
    assert verdicts["audio_channels"] == "mismatch"


def test_compare_unknown_when_actual_missing(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, container_id=1, video_codec_id=1, resolution_id=1)
    seeded.commit()
    exp = build_expected(seeded, it)
    actual = {"video": None, "audio": []}  # estrazione fallita / nessun video
    rep = compare_to_actual(exp, actual)
    verdicts = {f["field"]: f["verdict"] for f in rep["fields"]}
    assert verdicts["resolution"] == "unknown"
    assert verdicts["video_codec"] == "unknown"
    # unknown non conta come mismatch → ok resta True
    assert rep["ok"] is True


def test_compare_is_json_serializable(seeded, tenant_id):
    import json
    it = _mk_item(seeded, tenant_id, container_id=1, video_codec_id=1, resolution_id=1)
    seeded.commit()
    exp = build_expected(seeded, it)
    json.dumps(compare_to_actual(exp, {"video": {"width": 1920, "height": 1080}, "audio": []}))
