"""F2 (spec 2026-06-10) — Watch cartelle output (polling listing).

Stato in-memory per volume: {rel_path: size}. Un file è "stabile" (→ proposto)
quando appare con la STESSA size in due cicli consecutivi e non è già stato
proposto. Package DCP/IMF (cartella con ASSETMAP) = unità singola. Nessun
import di app.*: gira sull'agent facility.
"""
from __future__ import annotations
import os

from agent.probe import build_probe_result


class WatchState:
    """Stato osservazioni precedenti + set già-proposti (per volume)."""
    def __init__(self):
        self.prev_sizes: dict[str, int] = {}
        self.proposed: set[str] = set()


def is_dcp_package(dir_path: str) -> bool:
    try:
        names = {n.upper() for n in os.listdir(dir_path)}
    except OSError:
        return False
    return "ASSETMAP" in names or "ASSETMAP.XML" in names


def _dir_size(dir_path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(dir_path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total


def scan_volume(mount_path: str, watch_dirs: list[str],
                state: WatchState) -> list[dict]:
    """Un ciclo di scan. Ritorna i probe-result dei file/package NUOVI e
    stabili. Aggiorna lo state. Mai solleva: errori per-path isolati."""
    current: dict[str, int] = {}
    package_dirs: set[str] = set()
    new_results: list[dict] = []

    roots = watch_dirs or [""]
    for wd in roots:
        base = os.path.join(mount_path, wd.strip("/\\")) if wd else mount_path
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            if is_dcp_package(root):
                rel = os.path.relpath(root, mount_path).replace("\\", "/")
                current[rel] = _dir_size(root)
                package_dirs.add(rel)
                dirs[:] = []
                continue
            for fn in files:
                full = os.path.join(root, fn)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                rel = os.path.relpath(full, mount_path).replace("\\", "/")
                current[rel] = size

    for rel, size in current.items():
        if rel in state.proposed:
            continue
        prev = state.prev_sizes.get(rel)
        if prev is not None and prev == size:
            try:
                if rel in package_dirs:
                    res = _probe_package(mount_path, rel, size)
                else:
                    res = build_probe_result(mount_path, rel)
                new_results.append(res)
                state.proposed.add(rel)
            except (OSError, FileNotFoundError):
                pass
    state.prev_sizes = current
    return new_results


def _probe_package(mount_path: str, rel_dir: str, size: int) -> dict:
    """Package DCP/IMF: prova a probare il .mxf più grande, altrimenti
    metadata di cartella (tool=package)."""
    full_dir = os.path.join(mount_path, rel_dir)
    biggest = None
    biggest_sz = -1
    for root, _d, files in os.walk(full_dir):
        for fn in files:
            if fn.lower().endswith(".mxf"):
                p = os.path.join(root, fn)
                try:
                    s = os.path.getsize(p)
                except OSError:
                    continue
                if s > biggest_sz:
                    biggest_sz, biggest = s, p
    if biggest:
        rel_mxf = os.path.relpath(biggest, mount_path).replace("\\", "/")
        res = build_probe_result(mount_path, rel_mxf)
        res["rel_path"] = rel_dir
        res["file_size"] = size
        res["mime_type"] = "application/mxf"
        res.setdefault("tech_specs", {})["package"] = "dcp_imf"
        return res
    return {"rel_path": rel_dir, "file_size": size,
            "mime_type": "application/octet-stream", "checksum_xxhash": "",
            "tech_specs": {"tool": "package", "package": "dcp_imf"}}
