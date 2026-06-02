"""v3.5.0-alpha.172.164 — Test utility SMPTE timecode (app/services/timecode.py)."""
import pytest
from app.services.timecode import (
    parse_tc, is_valid_tc, normalize_tc, tc_to_frames, frames_to_tc, add_frames,
)


# ───────── parse / validate ─────────

def test_parse_basic():
    t = parse_tc("00:59:59:00")
    assert (t["hh"], t["mm"], t["ss"], t["ff"], t["drop"]) == (0, 59, 59, 0, False)


def test_parse_dropframe_separator():
    assert parse_tc("01:00:00;15")["drop"] is True


def test_parse_malformed_raises():
    for bad in ("", "abc", "1:2:3", "00-00-00-00", None):
        with pytest.raises(ValueError):
            parse_tc(bad)


def test_valid_ranges():
    assert is_valid_tc("00:59:59:00")
    assert is_valid_tc("23:59:59:24", fps=25)
    # HH=59 → invalido (il bug del template Vision)
    assert not is_valid_tc("59:59:00:00")
    # MM/SS 60 invalidi
    assert not is_valid_tc("00:60:00:00")
    assert not is_valid_tc("00:00:60:00")
    # FF >= fps invalido
    assert not is_valid_tc("00:00:00:25", fps=25)
    assert is_valid_tc("00:00:00:24", fps=25)


def test_valid_dropframe_skipped_frames():
    # @29.97 DF i frame 00/01 a inizio minuto (non %10) NON esistono
    assert not is_valid_tc("00:01:00;00", fps=29.97, drop=True)
    assert not is_valid_tc("00:01:00;01", fps=29.97, drop=True)
    assert is_valid_tc("00:01:00;02", fps=29.97, drop=True)
    # minuto 10 → nessun salto
    assert is_valid_tc("00:10:00;00", fps=29.97, drop=True)


# ───────── normalize ─────────

def test_normalize_padding():
    assert normalize_tc("1:2:3:4") == "01:02:03:04"


def test_normalize_dropframe_sep():
    assert normalize_tc("01:00:00;5") == "01:00:00;05"


def test_normalize_empty_none():
    assert normalize_tc("") is None
    assert normalize_tc(None) is None


def test_normalize_out_of_range_raises():
    with pytest.raises(ValueError):
        normalize_tc("59:59:00:00")  # HH=59


# ───────── frames conversion (non-drop) ─────────

def test_tc_to_frames_ndf():
    assert tc_to_frames("00:00:01:00", 25) == 25
    assert tc_to_frames("01:00:00:00", 24) == 24 * 3600
    assert tc_to_frames("00:00:00:10", 30) == 10


def test_roundtrip_ndf():
    for tc, fps in [("00:59:59:00", 25), ("01:00:00:00", 24), ("12:34:56:18", 30)]:
        n = tc_to_frames(tc, fps)
        assert frames_to_tc(n, fps) == tc


def test_add_frames_ndf_rollover():
    # 24 fps: 00:00:00:23 + 1 → 00:00:01:00
    assert add_frames("00:00:00:23", 1, 24) == "00:00:01:00"
    # 25 fps: 00:00:59:24 + 1 → 00:01:00:00
    assert add_frames("00:00:59:24", 1, 25) == "00:01:00:00"


# ───────── drop-frame conversion ─────────

def test_dropframe_minute_skip():
    # 00:00:59;29 + 1 frame → 00:01:00;02 (frame 00,01 saltati)
    assert add_frames("00:00:59;29", 1, 29.97, drop=True) == "00:01:00;02"


def test_dropframe_tenth_minute_no_skip():
    # 00:09:59;29 + 1 → 00:10:00;00 (minuto 10 → nessun salto)
    assert add_frames("00:09:59;29", 1, 29.97, drop=True) == "00:10:00;00"


def test_dropframe_roundtrip():
    for tc in ["00:01:00;02", "00:10:00;00", "01:00:00;00", "00:09:59;29"]:
        n = tc_to_frames(tc, 29.97, drop=True)
        assert frames_to_tc(n, 29.97, drop=True) == tc


def test_dropframe_realtime_accuracy():
    # 1 ora di drop-frame ≈ 107892 frame (vs 108000 nominali, -108)
    assert tc_to_frames("01:00:00;00", 29.97, drop=True) == 30 * 3600 - 2 * 9 * 6
