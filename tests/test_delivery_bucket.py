"""F1 pipeline deliverables — test bucket_key + match_or_create_bucket.

`compute_bucket(db, item)` riduce un DeliveryItem a una voce-bucket di listino
GENERICA, ramificando per media_kind (decisione 11 della spec
docs/superpowers/specs/2026-05-29-deliverables-pipeline-design.md):
- video  → (package|container) + codec + risoluzione + HDR
- audio  → mix_type/role + channel_config (traccia primaria)
- sidecar (subtitle/key/disc/document) → per tipo container

`match_or_create_bucket(db, tenant_id, item, category_id)` trova-o-crea il
PriceItem corrispondente (match per name entro la categoria) e lo ritorna.
"""
import pytest
from app.models.models import (
    Tenant, PriceCategory, PriceItem,
    DeliveryTemplate, DeliveryItem, AudioTrackSpec,
    Package, Container, VideoCodec, Resolution,
    AudioMixType, AudioChannelConfig,
)
from app.services.delivery_bucket import (
    compute_bucket, match_or_create_bucket, template_bucket_options,
)


@pytest.fixture
def seeded(db, tenant_id):
    """Taxonomy minima + 1 template per ancorare i DeliveryItem."""
    db.add(Tenant(id=tenant_id, name="T", slug="t"))
    # containers con media_kind
    qt = Container(id=1, tenant_id=tenant_id, name="QuickTime", media_kind="mixed")
    wav = Container(id=2, tenant_id=tenant_id, name="WAV", media_kind="audio")
    stl = Container(id=3, tenant_id=tenant_id, name="Subtitle Sidecar (EBU-STL)", media_kind="subtitle")
    kdm = Container(id=4, tenant_id=tenant_id, name="KDM / DKDM", media_kind="key")
    db.add_all([qt, wav, stl, kdm])
    # packages
    db.add(Package(id=1, tenant_id=tenant_id, name="DCP SMPTE"))
    # codecs
    db.add_all([
        VideoCodec(id=1, tenant_id=tenant_id, name="Apple ProRes 422 HQ"),
        VideoCodec(id=2, tenant_id=tenant_id, name="JPEG 2000 (DCP)"),
    ])
    # resolutions
    db.add_all([
        Resolution(id=1, tenant_id=tenant_id, name="HD 1080p", width=1920, height=1080),
        Resolution(id=2, tenant_id=tenant_id, name="UHD 3840", width=3840, height=2160),
        Resolution(id=3, tenant_id=tenant_id, name="2K DCI Scope", width=2048, height=858),
    ])
    # audio taxonomy
    db.add_all([
        AudioMixType(id=1, tenant_id=tenant_id, name="Full Mix (Final Mix)"),
        AudioMixType(id=2, tenant_id=tenant_id, name="M&E (Music + Effects)"),
        AudioChannelConfig(id=1, tenant_id=tenant_id, name="5.1 SMPTE", channel_count=6),
        AudioChannelConfig(id=2, tenant_id=tenant_id, name="Stereo 2.0", channel_count=2),
    ])
    db.add(DeliveryTemplate(id=1, tenant_id=tenant_id, code="T1", name="Tmpl"))
    db.commit()
    return db


def _mk_item(db, tenant_id, **kw):
    it = DeliveryItem(tenant_id=tenant_id, delivery_template_id=1, name=kw.pop("name", "x"), **kw)
    db.add(it)
    db.commit()
    return it


# ---------- compute_bucket: VIDEO ----------

def test_video_with_container_codec_res(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="Master ProRes",
                  container_id=1, video_codec_id=1, resolution_id=1)
    b = compute_bucket(seeded, it)
    assert b.group == "video"
    assert b.label == "QuickTime / Apple ProRes 422 HQ / HD 1080p"


def test_video_hdr_in_label(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="Master UHD HDR",
                  container_id=1, video_codec_id=1, resolution_id=2, hdr_format="HDR10")
    b = compute_bucket(seeded, it)
    assert b.label == "QuickTime / Apple ProRes 422 HQ / UHD 3840 / HDR10"


def test_video_sdr_not_in_label(seeded, tenant_id):
    """SDR/vuoto NON appare nel nome (decisione 8)."""
    it = _mk_item(seeded, tenant_id, name="Master SDR",
                  container_id=1, video_codec_id=1, resolution_id=2, hdr_format="SDR")
    b = compute_bucket(seeded, it)
    assert b.label == "QuickTime / Apple ProRes 422 HQ / UHD 3840"


def test_video_package_wins_over_container(seeded, tenant_id):
    """package presente → forma primaria = package (DCP), non container."""
    it = _mk_item(seeded, tenant_id, name="DCP",
                  package_id=1, container_id=1, video_codec_id=2, resolution_id=3)
    b = compute_bucket(seeded, it)
    assert b.group == "video"
    assert b.label == "DCP SMPTE / JPEG 2000 (DCP) / 2K DCI Scope"


# ---------- compute_bucket: AUDIO ----------

def test_audio_primary_track_mixtype_channel(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="Full Mix WAV", container_id=2)
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0,
                              track_label="Mix 5.1", mix_type_id=1, channel_config_id=1))
    seeded.commit()
    b = compute_bucket(seeded, it)
    assert b.group == "audio"
    assert b.label == "Full Mix (Final Mix) / 5.1 SMPTE"


def test_audio_me_stereo(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="M&E stereo", container_id=2)
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0,
                              track_label="M&E", mix_type_id=2, channel_config_id=2))
    seeded.commit()
    b = compute_bucket(seeded, it)
    assert b.label == "M&E (Music + Effects) / Stereo 2.0"


def test_audio_uses_lowest_sort_order_track(seeded, tenant_id):
    """La traccia primaria = sort_order minore, non l'ordine d'insert."""
    it = _mk_item(seeded, tenant_id, name="multi", container_id=2)
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=5,
                              track_label="ME", mix_type_id=2, channel_config_id=1))
    seeded.add(AudioTrackSpec(delivery_item_id=it.id, sort_order=0,
                              track_label="Mix", mix_type_id=1, channel_config_id=1))
    seeded.commit()
    b = compute_bucket(seeded, it)
    assert b.label == "Full Mix (Final Mix) / 5.1 SMPTE"


# ---------- compute_bucket: SIDECAR ----------

def test_subtitle_bucket(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="ST IT", container_id=3)
    b = compute_bucket(seeded, it)
    assert b.group == "subtitle"
    assert b.label == "Subtitle Sidecar (EBU-STL)"


def test_key_bucket(seeded, tenant_id):
    it = _mk_item(seeded, tenant_id, name="KDM", container_id=4)
    b = compute_bucket(seeded, it)
    assert b.group == "key"
    assert b.label == "KDM / DKDM"


# ---------- match_or_create_bucket ----------

def test_match_or_create_creates_then_reuses(seeded, tenant_id):
    cat = PriceCategory(tenant_id=tenant_id, name="Deliveries")
    seeded.add(cat)
    seeded.commit()
    it1 = _mk_item(seeded, tenant_id, name="a", container_id=1, video_codec_id=1, resolution_id=1)
    it2 = _mk_item(seeded, tenant_id, name="b", container_id=1, video_codec_id=1, resolution_id=1)
    p1 = match_or_create_bucket(seeded, tenant_id, it1, cat.id)
    p2 = match_or_create_bucket(seeded, tenant_id, it2, cat.id)
    assert p1.id == p2.id  # stessa tripla → stessa voce
    assert p1.name == "QuickTime / Apple ProRes 422 HQ / HD 1080p"
    assert p1.category_id == cat.id
    assert p1.unit  # unit obbligatorio popolato
    n = seeded.query(PriceItem).filter_by(category_id=cat.id).count()
    assert n == 1


def test_match_or_create_distinct_buckets(seeded, tenant_id):
    cat = PriceCategory(tenant_id=tenant_id, name="Deliveries")
    seeded.add(cat)
    seeded.commit()
    it1 = _mk_item(seeded, tenant_id, name="hd", container_id=1, video_codec_id=1, resolution_id=1)
    it2 = _mk_item(seeded, tenant_id, name="uhd", container_id=1, video_codec_id=1, resolution_id=2)
    p1 = match_or_create_bucket(seeded, tenant_id, it1, cat.id)
    p2 = match_or_create_bucket(seeded, tenant_id, it2, cat.id)
    assert p1.id != p2.id


# ---------- template_bucket_options (F2 picker source) ----------

def _link_bucket(db, tenant_id, cat_id, prices=None):
    """Crea items + linka via match_or_create + setta prezzi sulle voci."""
    pass


def test_template_bucket_options_groups_by_bucket(seeded, tenant_id):
    cat = PriceCategory(tenant_id=tenant_id, name="Deliveries")
    seeded.add(cat)
    seeded.commit()
    # 2 item stessa tripla → 1 bucket; 1 item tripla diversa → altro bucket
    it1 = _mk_item(seeded, tenant_id, name="ProRes A", container_id=1, video_codec_id=1, resolution_id=1, notes="Frame.io upload")
    it2 = _mk_item(seeded, tenant_id, name="ProRes B", container_id=1, video_codec_id=1, resolution_id=1, notes="naming X_Y_Z")
    it3 = _mk_item(seeded, tenant_id, name="UHD", container_id=1, video_codec_id=1, resolution_id=2)
    for it in (it1, it2, it3):
        pi = match_or_create_bucket(seeded, tenant_id, it, cat.id)
        it.suggested_price_item_id = pi.id
    seeded.commit()

    opts = template_bucket_options(seeded, tenant_id, template_id=1)
    # 2 bucket distinti
    assert len(opts) == 2
    by_name = {o["name"]: o for o in opts}
    hd = by_name["QuickTime / Apple ProRes 422 HQ / HD 1080p"]
    assert hd["item_count"] == 2
    assert set(hd["item_names"]) == {"ProRes A", "ProRes B"}
    # detail_suggestion compila le notes del capitolato
    assert "Frame.io upload" in hd["detail_suggestion"]
    assert "naming X_Y_Z" in hd["detail_suggestion"]
    assert hd["price_item_id"] > 0
    assert hd["unit"]


def test_template_bucket_options_sorted_and_skips_unlinked(seeded, tenant_id):
    cat = PriceCategory(tenant_id=tenant_id, name="Deliveries")
    seeded.add(cat)
    seeded.commit()
    linked = _mk_item(seeded, tenant_id, name="linked", container_id=1, video_codec_id=1, resolution_id=1)
    pi = match_or_create_bucket(seeded, tenant_id, linked, cat.id)
    linked.suggested_price_item_id = pi.id
    # item senza link → escluso
    _mk_item(seeded, tenant_id, name="orphan", container_id=1, video_codec_id=1, resolution_id=2)
    seeded.commit()
    opts = template_bucket_options(seeded, tenant_id, template_id=1)
    assert len(opts) == 1
    assert opts[0]["name"] == "QuickTime / Apple ProRes 422 HQ / HD 1080p"


def test_template_bucket_options_empty_template(seeded, tenant_id):
    assert template_bucket_options(seeded, tenant_id, template_id=999) == []
