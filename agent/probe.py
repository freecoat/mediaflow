"""Probe locale: ffprobe JSON + xxhash64. Nessun byte lascia la facility."""
from __future__ import annotations
import json
import mimetypes
import os
import subprocess
from typing import Optional

import xxhash

_CHUNK = 8 * 1024 * 1024


def run_ffprobe(path: str) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe rc={out.returncode}: {out.stderr[:500]}")
    return json.loads(out.stdout or "{}")


def normalize_ffprobe(raw: dict) -> dict:
    fmt = raw.get("format") or {}
    specs = {
        "tool": "ffprobe",
        "container": fmt.get("format_name"),
        "duration_sec": float(fmt["duration"]) if fmt.get("duration") else None,
        "video": None,
        "audio": [],
        "errors": [],
    }
    for s in raw.get("streams") or []:
        if s.get("codec_type") == "video" and specs["video"] is None:
            specs["video"] = {
                "codec": s.get("codec_name"), "width": s.get("width"),
                "height": s.get("height"), "frame_rate": s.get("r_frame_rate"),
                "pix_fmt": s.get("pix_fmt"),
            }
        elif s.get("codec_type") == "audio":
            specs["audio"].append({
                "codec": s.get("codec_name"), "channels": s.get("channels"),
                "sample_rate": s.get("sample_rate"),
            })
    return specs


def xxhash_file(path: str) -> str:
    h = xxhash.xxh64()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def build_probe_result(mount_path: str, rel_path: str) -> dict:
    full = os.path.join(mount_path, rel_path)
    if not os.path.isfile(full):
        raise FileNotFoundError(f"non trovato: {full}")
    mime, _ = mimetypes.guess_type(rel_path)
    try:
        specs = normalize_ffprobe(run_ffprobe(full))
    except Exception as e:
        specs = {"tool": "none", "errors": [str(e)[:300]]}
    return {
        "rel_path": rel_path.replace("\\", "/"),
        "file_size": os.path.getsize(full),
        "mime_type": mime or "application/octet-stream",
        "checksum_xxhash": xxhash_file(full),
        "tech_specs": specs,
    }
