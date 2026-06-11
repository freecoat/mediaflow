"""F3 — builder ffmpeg agent-side (puro, nessuna esecuzione)."""
import os
import shutil
import time

import pytest

from agent.preview import build_ffmpeg_cmd, probe_start_tc, generate_preview, upload_preview


def test_probe_start_tc_from_format_tags():
    probe = {"format": {"tags": {"timecode": "09:59:50:00"}},
             "streams": [{"codec_type": "video", "r_frame_rate": "25/1"}]}
    tc, rate = probe_start_tc(probe)
    assert tc == "09:59:50:00"
    assert rate == "25/1"


def test_probe_start_tc_fallback():
    probe = {"format": {}, "streams": [{"codec_type": "video",
                                        "r_frame_rate": "24000/1001"}]}
    tc, rate = probe_start_tc(probe)
    assert tc == "00:00:00:00"
    assert rate == "24000/1001"


def test_build_cmd_has_scale_codec_faststart():
    cmd = build_ffmpeg_cmd("/in.mxf", "/out.mp4", start_tc="10:00:00:00",
                           rate="25/1", tenant_name="TPR", burn=True)
    s = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "/in.mxf" in cmd and "/out.mp4" in cmd
    assert "scale=-2:1080" in s
    assert "libx264" in s and "aac" in s and "+faststart" in s
    assert "-ac" in cmd


def test_build_cmd_tc_escaped_and_watermark():
    cmd = build_ffmpeg_cmd("/i", "/o", start_tc="10:00:00:00", rate="25/1",
                           tenant_name="TPR Berlin", burn=True)
    vf = cmd[cmd.index("-vf") + 1]
    assert r"10\:00\:00\:00" in vf
    assert "timecode_rate=25/1" in vf
    assert "PREVIEW" in vf and "TPR Berlin" in vf


def test_build_cmd_no_burn_has_no_drawtext():
    cmd = build_ffmpeg_cmd("/i", "/o", start_tc="00:00:00:00", rate="25/1",
                           tenant_name="X", burn=False)
    vf = cmd[cmd.index("-vf") + 1]
    assert "drawtext" not in vf
    assert "scale=-2:1080" in vf


# ── Fix 1: escaping drawtext ──────────────────────────────────────────────────

def test_watermark_escaping_special_chars():
    """D'Amore, Post:Prod — backslash, colon, apostrophe, comma all escaped."""
    tenant = "D'Amore, Post:Prod"
    cmd = build_ffmpeg_cmd("/i", "/o", start_tc="00:00:00:00", rate="25/1",
                           tenant_name=tenant, burn=True)
    vf = cmd[cmd.index("-vf") + 1]

    # apostrophe must be escaped
    assert r"\'" in vf
    # colon in tenant name must be escaped (not inside timecode filter)
    assert r"\:" in vf
    # comma in tenant name must be escaped so it doesn't split the filtergraph
    assert r"\," in vf
    # splitting on unescaped commas must yield exactly 3 filters:
    # scale, drawtext(tc), drawtext(watermark)
    import re
    # unescaped comma = comma NOT preceded by backslash
    unescaped_commas = len(re.findall(r'(?<!\\),', vf))
    assert unescaped_commas == 2, (
        f"expected 2 unescaped commas (3 filters), got {unescaped_commas}: {vf!r}"
    )
    # the escaped text must contain the full name with escaping
    assert r"D\'Amore\, Post\:Prod" in vf


# ── Fix 2: missing binaries → clear error ────────────────────────────────────

def test_generate_preview_raises_when_ffmpeg_missing(tmp_path, monkeypatch):
    """If ffmpeg/ffprobe not in PATH, raise RuntimeError with helpful message."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    fake_src = tmp_path / "video.mxf"
    fake_src.write_bytes(b"\x00")
    with pytest.raises(RuntimeError, match="ffmpeg/ffprobe non trovato"):
        generate_preview(str(tmp_path), "video.mxf", "Tenant", str(tmp_path))


def test_generate_preview_raises_when_ffprobe_missing(tmp_path, monkeypatch):
    """If only ffprobe is missing, still raise RuntimeError."""
    monkeypatch.setattr(shutil, "which",
                        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    fake_src = tmp_path / "video.mxf"
    fake_src.write_bytes(b"\x00")
    with pytest.raises(RuntimeError, match="ffmpeg/ffprobe non trovato"):
        generate_preview(str(tmp_path), "video.mxf", "Tenant", str(tmp_path))


# ── Fix 4: upload retry ───────────────────────────────────────────────────────

def test_upload_retry_succeeds_after_two_failures(tmp_path, monkeypatch):
    """Client fails twice then succeeds → returns 'server', 3 total calls."""
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"fake")

    call_count = [0]

    class FakeClient:
        def put_preview(self, job_id, path):
            call_count[0] += 1
            if call_count[0] < 3:
                raise IOError("network blip")
            return {"ok": True}

    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))

    result = upload_preview(
        str(preview_file),
        job_id=42,
        upload_cfg={"mode": "server"},
        client=FakeClient(),
    )

    assert result == "server"
    assert call_count[0] == 3
    assert len(slept) == 2  # slept between attempts 1→2 and 2→3


def test_upload_retry_reraises_after_three_failures(tmp_path, monkeypatch):
    """After 3 failures the exception propagates."""
    preview_file = tmp_path / "preview.mp4"
    preview_file.write_bytes(b"fake")

    class FakeClient:
        def put_preview(self, job_id, path):
            raise IOError("always fails")

    monkeypatch.setattr(time, "sleep", lambda s: None)

    with pytest.raises(IOError, match="always fails"):
        upload_preview(
            str(preview_file),
            job_id=99,
            upload_cfg={"mode": "server"},
            client=FakeClient(),
        )
