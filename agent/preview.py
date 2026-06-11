"""Generazione proxy preview QC: ffmpeg 1080p + TC burn-in + watermark.

Nessun byte del master lascia la facility: esce solo il proxy watermarked,
verso il server Claqo o S3 (presigned), come deciso dal payload del job.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from agent.probe import run_ffprobe

# Retry policy for upload (seconds between attempts)
_RETRY_DELAYS = (5, 15)  # 2 delays → 3 total attempts


def _sanitize_drawtext(text: str) -> str:
    """Escape special chars for ffmpeg drawtext filter value.

    Order matters:
      1. backslash first (avoid double-escaping later substitutions)
      2. colon  → \\:
      3. apostrophe → \\'
      4. comma  → \\,  (comma is the filtergraph separator)
    """
    text = text.replace("\\", "\\\\")
    text = text.replace(":", r"\:")
    text = text.replace("'", r"\'")
    text = text.replace(",", r"\,")
    return text


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


def _find_fontfile() -> str | None:
    """Font di sistema per drawtext: su Windows le build ffmpeg comuni (Gyan)
    non hanno una config fontconfig e CRASHANO senza fontfile esplicito."""
    candidates = (
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def build_ffmpeg_cmd(src, dst, *, start_tc, rate, tenant_name, burn,
                     fontfile: str | None = None):
    filters = ["scale=-2:1080"]
    if burn:
        font = ""
        if fontfile:
            font = f"fontfile='{_sanitize_drawtext(fontfile)}':"
        tc_esc = start_tc.replace(":", r"\:")
        filters.append(
            f"drawtext={font}timecode='{tc_esc}':timecode_rate={rate}"
            ":fontsize=h/28:fontcolor=white:box=1:boxcolor=black@0.45"
            ":x=(w-tw)/2:y=h*0.03")
        wm = _sanitize_drawtext(f"PREVIEW - QC ONLY - {tenant_name}")
        filters.append(
            f"drawtext={font}text='{wm}'"
            ":fontsize=h/16:fontcolor=white@0.18:x=(w-tw)/2:y=(h-th)/2")
    return ["ffmpeg", "-y", "-i", src,
            "-vf", ",".join(filters),
            "-c:v", "libx264", "-crf", "20", "-preset", "medium",
            "-maxrate", "6M", "-bufsize", "12M",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-movflags", "+faststart", dst]


def generate_preview(mount_path: str, rel_path: str, tenant_name: str, workdir: str):
    """Genera proxy 1080p in workdir. Ritorna (dst_path, meta_dict)."""
    # Fix 2: guard binaries before doing anything
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffmpeg/ffprobe non trovato nel PATH — preview non disponibile su questo agent"
        )

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

    # Primo tentativo: TC burn-in attivo (fontfile esplicito: senza, le build
    # Windows crashano in fontconfig — visto live con Gyan 8.1.1, rc=0xC0000005)
    cmd = build_ffmpeg_cmd(src, dst, start_tc=start_tc, rate=rate,
                           tenant_name=tenant_name, burn=True,
                           fontfile=_find_fontfile())
    # Fix 5: explicit encoding to avoid cp1252 UnicodeDecodeError on Windows
    proc = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=14400)
    burned_tc = True

    if proc.returncode != 0:
        # Qualsiasi errore col burn attivo (fontconfig assente, drawtext non
        # compilato, crash): riprova senza burn — meglio un proxy senza TC
        # che nessun proxy. Se fallisce anche così, l'errore sotto è quello vero.
        cmd_nb = build_ffmpeg_cmd(src, dst, start_tc=start_tc, rate=rate,
                                  tenant_name=tenant_name, burn=False)
        proc = subprocess.run(cmd_nb, capture_output=True, encoding="utf-8",
                              errors="replace", timeout=14400)
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
    """Carica il proxy. Ritorna "s3" o "server".

    Retry 3 tentativi totali (2 retry) con sleep 5s poi 15s tra i tentativi.
    """
    mode = (upload_cfg or {}).get("mode", "server")

    last_exc: Exception | None = None
    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        try:
            if mode == "s3":
                import requests
                put_url = upload_cfg["put_url"]
                # Fix 3: include Content-Length so S3 presigned PUT accepts the body
                size = os.path.getsize(path)
                with open(path, "rb") as fh:
                    requests.put(put_url, data=fh,
                                 headers={"Content-Type": "video/mp4",
                                          "Content-Length": str(size)},
                                 timeout=3600).raise_for_status()
                return "s3"
            else:
                # default: upload al server Claqo
                client.put_preview(job_id, path)
                return "server"
        except Exception as exc:
            last_exc = exc
            if delay is not None:
                time.sleep(delay)

    raise last_exc  # type: ignore[misc]
