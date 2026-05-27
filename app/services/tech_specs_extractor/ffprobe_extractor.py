"""Bundle L Stack 1 — FFProbeExtractor: porting da asset_metadata.py.

Estrae specs video/audio via ffprobe (subprocess, no dipendenze Python aggiunte).
Gentle fallback se ffprobe non installato → errors[].
"""
from __future__ import annotations

import json as _json
import shutil
import subprocess
from typing import Optional

from app.services.tech_specs_extractor import register_extractor
from app.services.tech_specs_extractor.base import TechSpecsExtractor


def _parse_framerate(rate_str: str) -> Optional[str]:
    if not rate_str or "/" not in rate_str:
        return rate_str or None
    try:
        num, den = rate_str.split("/")
        n, d = float(num), float(den)
        if d == 0:
            return None
        val = n / d
        return f"{val:.3f}".rstrip("0").rstrip(".") if val != int(val) else str(int(val))
    except Exception:
        return rate_str


@register_extractor(name="ffprobe", mime_priority=["video/*", "audio/*"])
class FFProbeExtractor(TechSpecsExtractor):
    def extract(self, path: str, mime: Optional[str] = None) -> dict:
        out = {"tool": "ffprobe", "container": None, "video": None, "audio": [], "errors": []}
        if shutil.which("ffprobe") is None:
            out["errors"].append("ffprobe non installato su questo sistema")
            return out
        try:
            cmd = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=8, check=False)
            if res.returncode != 0:
                out["errors"].append(f"ffprobe rc={res.returncode}: {(res.stderr or '').strip()[:200]}")
                return out
            data = _json.loads(res.stdout or "{}")
        except subprocess.TimeoutExpired:
            out["errors"].append("ffprobe timeout dopo 8s")
            return out
        except Exception as e:
            out["errors"].append(f"ffprobe exception: {type(e).__name__}: {e}")
            return out

        fmt = data.get("format") or {}
        out["container"] = {
            "format": fmt.get("format_name"),
            "size_bytes": int(fmt.get("size", 0)) if fmt.get("size") else None,
            "duration_sec": float(fmt.get("duration", 0)) if fmt.get("duration") else None,
            "bitrate_kbps": int(int(fmt.get("bit_rate", 0)) / 1000) if fmt.get("bit_rate") else None,
        }
        for stream in (data.get("streams") or []):
            ct = stream.get("codec_type")
            if ct == "video" and out["video"] is None:
                out["video"] = {
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "framerate": _parse_framerate(stream.get("r_frame_rate", "")),
                    "codec": stream.get("codec_name"),
                    "duration_sec": float(stream["duration"]) if stream.get("duration") else None,
                    "bitrate_kbps": int(int(stream["bit_rate"]) / 1000) if stream.get("bit_rate") else None,
                    "pixel_format": stream.get("pix_fmt"),
                }
            elif ct == "audio":
                out["audio"].append({
                    "codec": stream.get("codec_name"),
                    "channels": stream.get("channels"),
                    "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                    "bitrate_kbps": int(int(stream["bit_rate"]) / 1000) if stream.get("bit_rate") else None,
                    "language": (stream.get("tags") or {}).get("language"),
                })
        return out
