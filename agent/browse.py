"""Listing directory per il file-browser della UI /storage.

Solo nomi/dimensioni: nessun contenuto lascia la facility.
"""
from __future__ import annotations
import os

MAX_ENTRIES = 500


def list_dir(mount_path: str, rel_path: str = "",
             max_entries: int = MAX_ENTRIES) -> dict:
    """Lista una directory dentro il volume. Dirs prima, poi file, alfabetico.

    Solleva ValueError se il path risolto esce dal mount (traversal),
    FileNotFoundError se la directory non esiste.
    """
    rel = (rel_path or "").strip().strip("/\\")
    base = os.path.realpath(mount_path)
    full = os.path.realpath(os.path.join(base, rel)) if rel else base
    if full != base and not full.startswith(base + os.sep):
        raise ValueError(f"percorso fuori dal volume: {rel_path!r}")
    if not os.path.isdir(full):
        raise FileNotFoundError(f"directory non trovata: {rel or '/'}")
    entries = []
    with os.scandir(full) as it:
        for e in it:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                size = None if is_dir else e.stat(follow_symlinks=False).st_size
            except OSError:
                continue  # file sparito/illeggibile durante lo scan
            entries.append({"name": e.name, "is_dir": is_dir, "size": size})
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return {
        "rel_path": rel.replace("\\", "/"),
        "entries": entries[:max_entries],
        "truncated": len(entries) > max_entries,
    }
