# tests/test_cpl_parser.py
from pathlib import Path
import pytest
from app.services.cpl_parser import parse_cpl

FX = Path(__file__).parent / "fixtures"


def test_parse_smpte_encrypted():
    r = parse_cpl((FX / "cpl_smpte.xml").read_bytes())
    assert r["cpl_uuid"] == "urn:uuid:6c9f1f2e-1111-4aaa-bbbb-000000000001"
    assert "QUEER_FTR" in r["content_title_text"]
    assert r["edit_rate"] == "24 1"
    assert r["duration_frames"] == 1440
    assert r["encrypted"] is True
    assert len(r["key_ids"]) == 2


def test_parse_interop_unencrypted():
    r = parse_cpl((FX / "cpl_interop.xml").read_bytes())
    assert r["cpl_uuid"].endswith("000000000002")
    assert r["encrypted"] is False
    assert r["key_ids"] == []


def test_parse_non_cpl_raises():
    with pytest.raises(ValueError):
        parse_cpl(b"<Foo/>")


def test_billion_laughs_rejected():
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
        b'<CompositionPlaylist><ContentTitleText>&lol3;</ContentTitleText></CompositionPlaylist>'
    )
    with pytest.raises(ValueError):
        parse_cpl(payload)


def test_xxe_external_entity_rejected():
    payload = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<CompositionPlaylist><Id>&x;</Id></CompositionPlaylist>'
    )
    with pytest.raises(ValueError):
        parse_cpl(payload)
