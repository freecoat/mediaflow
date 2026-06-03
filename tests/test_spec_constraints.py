"""Vincoli specs per tipo file (α.172.183): field_relevance + coerenza."""
from app.services import delivery_item_validation as dv


def test_audio_container_hides_video_and_color():
    g = dv.field_relevance(media_kind="audio", has_package=False,
                           video_codec_family=None, has_audio=True)
    assert g["video"] == "hide"
    assert g["color"] == "hide"
    assert g["audio"] == "show"


def test_image_seq_hides_audio():
    g = dv.field_relevance(media_kind="image_seq", has_package=False,
                           video_codec_family="jpeg2000", has_audio=False)
    assert g["audio"] == "hide"
    assert g["video"] == "show"


def test_video_with_audio_shows_both():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=True)
    assert g["video"] == "show"
    assert g["audio"] == "show"


def test_video_without_audio_hides_audio():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=False)
    assert g["audio"] == "hide"


def test_no_package_hides_package():
    g = dv.field_relevance(media_kind="video", has_package=False,
                           video_codec_family="prores", has_audio=True)
    assert g["package"] == "hide"


def test_with_package_shows_package():
    g = dv.field_relevance(media_kind="video", has_package=True,
                           video_codec_family="jpeg2000", has_audio=False)
    assert g["package"] == "show"


def test_unknown_media_kind_shows_all():
    g = dv.field_relevance(media_kind=None, has_package=False,
                           video_codec_family=None, has_audio=False)
    assert all(v == "show" for k, v in g.items() if k in ("video", "audio", "color"))
