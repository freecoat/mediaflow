"""F3 — builder ffmpeg agent-side (puro, nessuna esecuzione)."""
from agent.preview import build_ffmpeg_cmd, probe_start_tc


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
