"""Test extractor service registry + base ABC."""
import pytest


def test_extractor_abc_required_method():
    from app.services.tech_specs_extractor.base import TechSpecsExtractor

    class Incomplete(TechSpecsExtractor):
        pass

    with pytest.raises(TypeError):
        Incomplete()  # ABC: extract() non implementato


def test_register_and_lookup_extractor():
    from app.services.tech_specs_extractor import register_extractor, get_extractor
    from app.services.tech_specs_extractor.base import TechSpecsExtractor

    @register_extractor(name="dummy_test", mime_priority=["audio/*"])
    class DummyExtractor(TechSpecsExtractor):
        def extract(self, path, mime):
            return {"tool": "dummy_test"}

    found = get_extractor(mime="audio/wav")
    assert found is not None
    inst = found()
    assert inst.extract("/tmp/x.wav", "audio/wav") == {"tool": "dummy_test"}


def test_extract_tech_specs_public_api():
    from app.services.tech_specs_extractor import extract_tech_specs, register_extractor
    from app.services.tech_specs_extractor.base import TechSpecsExtractor

    @register_extractor(name="dummy_video", mime_priority=["video/*"])
    class DummyVideo(TechSpecsExtractor):
        def extract(self, path, mime):
            return {"tool": "dummy_video", "video": {"codec": "fake"}}

    out = extract_tech_specs("/tmp/x.mp4", "video/mp4")
    assert out["tool"] == "dummy_video"
    assert out["video"]["codec"] == "fake"


def test_no_extractor_returns_none_struct():
    from app.services.tech_specs_extractor import extract_tech_specs

    out = extract_tech_specs("/tmp/unknown.bin", "application/octet-stream")
    assert out["tool"] == "none"
    assert "errors" in out
