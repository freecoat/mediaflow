"""Asset metadata extractor (Bundle H3 — v3.5.0-alpha.172.92).

Estrae specifiche tecniche da file Asset:
- Video/audio: ffprobe (subprocess, no dipendenza Python aggiuntiva)
- Immagini: Pillow EXIF (gia' nelle deps tramite generate_thumbnail)
- PDF/altro: skip gracefully

Output normalizzato (subset utile per cost report / deliverable QC):
  {
    "tool": "ffprobe" | "pillow" | "none",
    "extracted_at": "ISO-8601",
    "video": {"width": 1920, "height": 1080, "framerate": "23.976",
              "codec": "h264", "duration_sec": 1234.5, "bitrate_kbps": 8500,
              "pixel_format": "yuv420p"},
    "audio": [{"codec": "aac", "channels": 2, "sample_rate": 48000,
               "bitrate_kbps": 256, "language": "ita"}, ...],
    "container": {"format": "mov,mp4,...", "size_bytes": 1234567890},
    "errors": ["..."]  # se ffprobe ha fallito, motivo
  }

Idempotente: caller può richiamare e riceve sempre lo stesso output.
NB: subprocess.run con timeout per evitare hang su file corrotti.
"""
from __future__ import annotations

import json as _json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _ffprobe_available() -> bool:
    """Check ffprobe nel PATH (cache lookup per evitare scan ripetuti)."""
    return shutil.which("ffprobe") is not None


def _parse_framerate(rate_str: str) -> Optional[str]:
    """Converte ffprobe 'r_frame_rate' (es. '24000/1001') in stringa
    leggibile ('23.976'). Ritorna None su input degenere."""
    if not rate_str or "/" not in rate_str:
        return rate_str or None
    try:
        num, den = rate_str.split("/")
        n, d = float(num), float(den)
        if d == 0:
            return None
        val = n / d
        # Restituisci valore con 3 decimali se non intero
        return f"{val:.3f}".rstrip("0").rstrip(".") if val != int(val) else str(int(val))
    except Exception:
        return rate_str


def _extract_with_ffprobe(file_path: str, timeout: int = 8) -> dict:
    """Esegue ffprobe -show_format -show_streams in JSON. Timeout 8s default."""
    out = {"tool": "ffprobe", "video": None, "audio": [], "container": None, "errors": []}
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_format", "-show_streams",
            "-of", "json", file_path,
        ]
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            check=False,  # non lanciare eccezione su exit code non-zero
        )
        if res.returncode != 0:
            out["errors"].append(f"ffprobe rc={res.returncode}: {(res.stderr or '').strip()[:200]}")
            return out
        data = _json.loads(res.stdout or "{}")
    except subprocess.TimeoutExpired:
        out["errors"].append(f"ffprobe timeout after {timeout}s")
        return out
    except Exception as e:
        out["errors"].append(f"ffprobe exception: {e}")
        return out

    fmt = data.get("format") or {}
    out["container"] = {
        "format": fmt.get("format_name"),
        "size_bytes": int(fmt.get("size", 0)) if fmt.get("size") else None,
        "duration_sec": float(fmt.get("duration", 0)) if fmt.get("duration") else None,
        "bitrate_kbps": int(int(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else None,
    }

    for stream in (data.get("streams") or []):
        codec_type = stream.get("codec_type")
        if codec_type == "video" and out["video"] is None:  # primo video stream
            out["video"] = {
                "width": stream.get("width"),
                "height": stream.get("height"),
                "framerate": _parse_framerate(stream.get("r_frame_rate", "")),
                "codec": stream.get("codec_name"),
                "duration_sec": float(stream["duration"]) if stream.get("duration") else None,
                "bitrate_kbps": int(int(stream["bit_rate"]) / 1000) if stream.get("bit_rate") else None,
                "pixel_format": stream.get("pix_fmt"),
                "color_space": stream.get("color_space"),
            }
        elif codec_type == "audio":
            out["audio"].append({
                "codec": stream.get("codec_name"),
                "channels": stream.get("channels"),
                "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                "bitrate_kbps": int(int(stream["bit_rate"]) / 1000) if stream.get("bit_rate") else None,
                "language": (stream.get("tags") or {}).get("language"),
            })

    return out


def _extract_with_pillow(file_path: str) -> dict:
    """Fallback per immagini quando ffprobe non disponibile o file = jpg/png."""
    out = {"tool": "pillow", "video": None, "audio": [], "container": None, "errors": []}
    try:
        from PIL import Image
        with Image.open(file_path) as img:
            out["video"] = {
                "width": img.width,
                "height": img.height,
                "framerate": None,
                "codec": img.format,
                "duration_sec": None,
                "bitrate_kbps": None,
                "pixel_format": img.mode,
                "color_space": None,
            }
            out["container"] = {
                "format": img.format,
                "size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else None,
                "duration_sec": None,
                "bitrate_kbps": None,
            }
    except Exception as e:
        out["errors"].append(f"Pillow exception: {e}")
    return out


def extract_asset_metadata(file_path: str, mime_type: Optional[str] = None) -> dict:
    """Entrypoint principale. Decide tool in base a mime_type/disponibilita'.

    Strategy:
    1. ffprobe disponibile + file esiste → ffprobe (gestisce TUTTI i media).
    2. mime image/* → Pillow fallback.
    3. else → metadata vuoto + tool=none.

    Sempre restituisce dict con shape consistente. NON solleva eccezioni.
    """
    base = {
        "tool": "none",
        "extracted_at": datetime.utcnow().isoformat() + "Z",
        "video": None,
        "audio": [],
        "container": None,
        "errors": [],
    }

    if not file_path:
        base["errors"].append("file_path vuoto")
        return base
    if not os.path.exists(file_path):
        base["errors"].append(f"file non trovato: {file_path}")
        return base

    # Try ffprobe per tutti i tipi (gestisce video/audio/anche alcuni image)
    if _ffprobe_available():
        result = _extract_with_ffprobe(file_path)
        result["extracted_at"] = base["extracted_at"]
        # Se ffprobe non ha estratto NIENTE (no video, no audio, no container)
        # e' un fallimento totale — try Pillow per immagini
        if not result["video"] and not result["audio"] and (mime_type or "").startswith("image/"):
            pillow_result = _extract_with_pillow(file_path)
            pillow_result["extracted_at"] = base["extracted_at"]
            pillow_result["errors"] = result["errors"] + pillow_result["errors"]
            return pillow_result
        return result

    # Fallback Pillow per immagini
    if (mime_type or "").startswith("image/"):
        result = _extract_with_pillow(file_path)
        result["extracted_at"] = base["extracted_at"]
        return result

    base["errors"].append("ffprobe non installato e file non e' immagine — metadata skip")
    return base
