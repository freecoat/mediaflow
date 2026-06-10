"""F1 — agent probe: normalizzazione ffprobe + xxhash file."""
import json
import pytest

from agent.probe import normalize_ffprobe, xxhash_file, build_probe_result


FFPROBE_OUT = {
    "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "60.5",
               "size": "1000000"},
    "streams": [
        {"codec_type": "video", "codec_name": "prores", "width": 1920,
         "height": 1080, "r_frame_rate": "25/1", "pix_fmt": "yuv422p10le"},
        {"codec_type": "audio", "codec_name": "pcm_s24le", "channels": 2,
         "sample_rate": "48000"},
    ],
}


def test_normalize_ffprobe():
    specs = normalize_ffprobe(FFPROBE_OUT)
    assert specs["tool"] == "ffprobe"
    assert specs["container"] == "mov,mp4,m4a,3gp,3g2,mj2"
    assert specs["duration_sec"] == pytest.approx(60.5)
    assert specs["video"]["codec"] == "prores"
    assert specs["video"]["width"] == 1920
    assert specs["video"]["frame_rate"] == "25/1"
    assert specs["audio"][0]["channels"] == 2


def test_xxhash_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"claqo" * 1000)
    h1 = xxhash_file(str(f))
    h2 = xxhash_file(str(f))
    assert h1 == h2
    assert len(h1) == 16


def test_build_probe_result(tmp_path, monkeypatch):
    f = tmp_path / "OUT" / "file.mov"
    f.parent.mkdir()
    f.write_bytes(b"finto contenuto")
    monkeypatch.setattr("agent.probe.run_ffprobe", lambda p: FFPROBE_OUT)
    res = build_probe_result(str(tmp_path), "OUT/file.mov")
    assert res["rel_path"] == "OUT/file.mov"
    assert res["file_size"] == 15
    assert res["mime_type"] == "video/quicktime"
    assert len(res["checksum_xxhash"]) == 16
    assert res["tech_specs"]["video"]["codec"] == "prores"
