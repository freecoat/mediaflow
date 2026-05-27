"""Test extractor service registry + base ABC."""
import pytest


@pytest.fixture(autouse=True)
def _clean_registry():
    """Svuota _REGISTRY prima di ogni test e ripristina lo snapshot dopo.

    Necessario perche' Task 8/9 registrano FFProbe/Pillow al boot
    su video/*, audio/*, image/*: senza cleanup, i Dummy registrati
    nei test non vincerebbero piu' first-match-wins.

    Pattern: i test che vogliono extractor "di produzione" devono
    ricaricare esplicitamente il modulo via `importlib.reload`, che
    ri-esegue il decorator @register_extractor.
    """
    from app.services.tech_specs_extractor import _REGISTRY
    snapshot = list(_REGISTRY)
    _REGISTRY.clear()
    yield
    _REGISTRY[:] = snapshot


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


def test_ffprobe_registered_for_video_audio():
    # Il fixture _clean_registry ha svuotato _REGISTRY: ricarico il modulo
    # ffprobe_extractor per riattivare il decorator @register_extractor.
    import importlib
    from app.services.tech_specs_extractor import ffprobe_extractor
    importlib.reload(ffprobe_extractor)
    from app.services.tech_specs_extractor import get_extractor

    assert get_extractor("video/mp4") is not None
    assert get_extractor("audio/wav") is not None
    assert get_extractor("video/quicktime") is not None


def test_ffprobe_missing_file_returns_error_struct():
    # Idem: ricarico per registrare ffprobe.
    import importlib
    from app.services.tech_specs_extractor import ffprobe_extractor
    importlib.reload(ffprobe_extractor)
    from app.services.tech_specs_extractor import extract_tech_specs
    out = extract_tech_specs("/non/existent/file.mp4", "video/mp4")
    assert out["tool"] in ("ffprobe", "none")  # ffprobe assente o file mancante
    assert isinstance(out.get("errors"), list)


def test_pillow_registered_for_images():
    # _clean_registry ha svuotato _REGISTRY: ricarico pillow_extractor
    # per riattivare il decorator @register_extractor.
    import importlib
    from app.services.tech_specs_extractor import pillow_extractor
    importlib.reload(pillow_extractor)
    from app.services.tech_specs_extractor import get_extractor
    assert get_extractor("image/jpeg") is not None
    assert get_extractor("image/png") is not None
