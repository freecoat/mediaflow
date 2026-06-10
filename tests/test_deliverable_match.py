"""F2 — scoring match probe vs deliverable atteso (puro, no DB)."""
from app.services.deliverable_match import (
    normalize_codec, score_naming, score_match, MatchExpectation, MatchResult,
)


PROBE = {
    "container": "mov,mp4,m4a,3gp,3g2,mj2",
    "video": {"codec": "prores", "width": 1920, "height": 1080,
              "frame_rate": "25/1"},
}


def test_normalize_codec_aliases():
    assert normalize_codec("prores") == "prores"
    assert normalize_codec("ProRes 422 HQ") == "prores"
    assert normalize_codec("h264") == "h264"
    assert normalize_codec("AVC") == "h264"


def test_score_naming_exact_and_token():
    assert score_naming("GOMORRA_S03_EP01_PRORES.mov",
                        "GOMORRA_S03_EP01") >= 0.8
    assert score_naming("random.mov", "GOMORRA_S03_EP01") < 0.3


def test_score_match_strong():
    exp = MatchExpectation(
        deliverable_id=10, file_naming="GOMORRA_S03_EP01",
        container_name="QuickTime", container_ext="mov",
        video_codec_name="ProRes 422 HQ", width=1920, height=1080, fps=25.0)
    r = score_match("GOMORRA_S03_EP01_PRORES.mov", PROBE, exp)
    assert isinstance(r, MatchResult)
    assert r.deliverable_id == 10
    assert r.strength == "strong"
    assert r.score >= 0.75


def test_score_match_weak():
    exp = MatchExpectation(
        deliverable_id=11, file_naming="ALTRO_TITOLO",
        container_name="QuickTime", container_ext="mov",
        video_codec_name="ProRes 422 HQ", width=1920, height=1080, fps=25.0)
    r = score_match("GOMORRA_S03_EP01_PRORES.mov", PROBE, exp)
    assert r.strength in ("weak", "none")
    assert r.score < 0.75


def test_score_match_zero_specs_missing():
    exp = MatchExpectation(deliverable_id=12, file_naming="X",
                           container_name=None, container_ext=None,
                           video_codec_name=None, width=None, height=None, fps=None)
    r = score_match("random.mov", PROBE, exp)
    assert r.strength == "none"
