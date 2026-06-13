"""delivery_item_validation — funzioni pure (no DB).

preferred_container_for_codec: dato il family del codec e la lista container,
ritorna l'id del container preferito (ProRes→QuickTime) o None.
"""
from app.services.delivery_item_validation import preferred_container_for_codec


class _C:
    def __init__(self, id, name, extension=None):
        self.id = id
        self.name = name
        self.extension = extension


def test_prores_prefers_quicktime_by_name():
    conts = [_C(1, "MXF OP1a"), _C(2, "QuickTime", ".mov"), _C(3, "MP4")]
    assert preferred_container_for_codec(codec_family="ProRes", containers=conts) == 2


def test_prores_prefers_by_mov_extension():
    conts = [_C(1, "MXF OP1a"), _C(7, "Movie wrapper", ".mov")]
    assert preferred_container_for_codec(codec_family="prores", containers=conts) == 7


def test_non_prores_family_returns_none():
    conts = [_C(2, "QuickTime", ".mov")]
    assert preferred_container_for_codec(codec_family="DNxHR", containers=conts) is None


def test_empty_family_returns_none():
    conts = [_C(2, "QuickTime", ".mov")]
    assert preferred_container_for_codec(codec_family="", containers=conts) is None
    assert preferred_container_for_codec(codec_family=None, containers=conts) is None


def test_prores_no_quicktime_available_returns_none():
    conts = [_C(1, "MXF OP1a"), _C(3, "MP4")]
    assert preferred_container_for_codec(codec_family="ProRes", containers=conts) is None


def test_accepts_dict_containers():
    conts = [{"id": 9, "name": "QuickTime", "extension": ".mov"}]
    assert preferred_container_for_codec(codec_family="ProRes", containers=conts) == 9
