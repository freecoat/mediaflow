"""Generazione proxy preview QC: ffmpeg 1080p + TC burn-in + watermark.

Nessun byte del master lascia la facility: esce solo il proxy watermarked,
verso il server Claqo o S3 (presigned), come deciso dal payload del job.
"""
from __future__ import annotations

import os
import subprocess

from agent.probe import run_ffprobe


def probe_start_tc(probe: dict) -> tuple[str, str]:
    """(start_tc, rate) dal JSON ffprobe. Fallback 00:00:00:00 / 25/1."""
    tags = (probe.get("format") or {}).get("tags") or {}
    tc = tags.get("timecode")
    rate = "25/1"
    for s in probe.get("streams") or []:
        if s.get("codec_type") == "video":
            if not tc:
                tc = (s.get("tags") or {}).get("timecode")
            rate = s.get("r_frame_rate") or rate
            break
    return (tc or "00:00:00:00"), rate


def build_ffmpeg_cmd(src, dst, *, start_tc, rate, tenant_name, burn):
    filters = ["scale=-2:1080"]
    if burn:
        tc_esc = start_tc.replace(":", r"\:")
        filters.append(
            f"drawtext=timecode='{tc_esc}':timecode_rate={rate}"
            ":fontsize=h/28:fontcolor=white:box=1:boxcolor=black@0.45"
            ":x=(w-tw)/2:y=h*0.03")
        wm = f"PREVIEW - QC ONLY - {tenant_name}".replace(":", r"\:").replace("'", "")
        filters.append(
            f"drawtext=text='{wm}'"
            ":fontsize=h/16:fontcolor=white@0.18:x=(w-tw)/2:y=(h-th)/2")
    return ["ffmpeg", "-y", "-i", src,
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-maxrate", "6M", "-bufsize", "12M",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-movflags", "+faststart", dst]


def generate_preview(mount_path: str, rel_path: str, tenant_name: str, workdir: str):
    """Genera proxy 1080p in workdir. Ritorna (dst_path, meta_dict)."""
    src = os.path.join(mount_path, rel_path)
    if not os.path.isfile(src):
        raise FileNotFoundError(f"sorgente non trovata: {src}")

    probe = run_ffprobe(src)
    start_tc, rate = probe_start_tc(probe)

    # durata tollerante: potrebbe mancare o essere stringa non numerica
    try:
        duration_sec = float((probe.get("format") or {}).get("duration") or 0) or None
    except (TypeError, ValueError):
        duration_sec = None

    dst = os.path.join(workdir, "preview.mp4")

    # Primo tentativo: TC burn-in attivo
    cmd = build_ffmpeg_cmd(src, dst, start_tc=start_tc, rate=rate,
                           tenant_name=tenant_name, burn=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
    burned_tc = True

    if proc.returncode != 0 and "drawtext" in proc.stderr:
        # ffmpeg senza fontconfig: riprova senza burn
        cmd_nb = build_ffmpeg_cmd(src, dst, start_tc=start_tc, rate=rate,
                                  tenant_name=tenant_name, burn=False)
        proc = subprocess.run(cmd_nb, capture_output=True, text=True, timeout=14400)
        burned_tc = False

    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg rc={proc.returncode}: {proc.stderr[-800:]}")

    meta = {
        "start_tc": start_tc,
        "fps": eval_rate(rate),
        "duration_sec": duration_sec,
        "burned_tc": burned_tc,
    }
    return dst, meta


def eval_rate(rate: str) -> float:
    num, _, den = rate.partition("/")
    return round(float(num) / float(den or 1), 3)


def upload_preview(path: str, *, job_id: int, upload_cfg: dict, client) -> str:
    """Carica il proxy. Ritorna "s3" o "server"."""
    mode = (upload_cfg or {}).get("mode", "server")
    if mode == "s3":
        import requests
        put_url = upload_cfg["put_url"]
        with open(path, "rb") as fh:
            requests.put(put_url, data=fh,
                         headers={"Content-Type": "video/mp4"},
                         timeout=3600).raise_for_status()
        return "s3"
    # default: upload al server Claqo
    client.put_preview(job_id, path)
    return "server"
