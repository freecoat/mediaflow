"""v3.5.0-alpha.75 — Filesystem scan tool per asset fisici.

Use case Matteo: HDD cliente in deposito → monta su path locale → "leggi
il disco" → walk + checksum → register Asset digital + AssetMembership.

Implementazione server-side: il path deve essere accessibile dal processo
FastAPI. Per setup esterno (es. macchina cliente) servirebbe agent locale
(scope futuro).

API exposed:
  POST /physical-assets/api/{id}/scan-content
    - path: stringa filesystem path (validata)
    - compute_checksum: bool (xxhash veloce, opzionale)
    - max_depth: int (default 8)
    - skip_patterns: lista glob (default ["__MACOSX","Thumbs.db",".DS_Store"])

  Walk + per ogni file:
    - dimensione, mtime
    - xxhash (se compute_checksum=True; usa pacchetto `xxhash`)
    - mime type guess
  Crea Asset placeholder + AssetMembership.
"""
from __future__ import annotations
import os
import mimetypes
from pathlib import Path
from typing import Iterable, Optional

# xxhash è veloce; fallback md5 se non disponibile
try:
    import xxhash  # type: ignore
    _HAS_XXHASH = True
except Exception:
    _HAS_XXHASH = False
    import hashlib


DEFAULT_SKIP = {
    "__MACOSX", "Thumbs.db", ".DS_Store", ".AppleDouble", ".LSOverride",
    "desktop.ini", "._" + "*",
}


def _hash_file(path: Path, max_bytes: int = 0) -> Optional[str]:
    """xxhash64 se disponibile, MD5 fallback. max_bytes=0 = whole file."""
    try:
        if _HAS_XXHASH:
            h = xxhash.xxh64()
        else:
            h = hashlib.md5()  # noqa: S324
        with open(path, "rb") as f:
            CHUNK = 1024 * 1024
            read_total = 0
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                read_total += len(chunk)
                if max_bytes and read_total >= max_bytes:
                    break
        return h.hexdigest()
    except OSError:
        return None


def _should_skip(name: str, patterns: Iterable[str]) -> bool:
    n = name.lower()
    for pat in patterns:
        p = pat.lower()
        if p.endswith("*") and n.startswith(p[:-1]):
            return True
        if p.startswith("*") and n.endswith(p[1:]):
            return True
        if p == n:
            return True
    return False


def walk_filesystem(
    root_path: str,
    *,
    compute_checksum: bool = False,
    max_depth: int = 8,
    skip_patterns: Optional[set] = None,
    max_files: int = 5000,
) -> dict:
    """Walk path + ritorna lista file con metadata. NON crea record DB —
    il caller usa il manifest per import o display.

    Output: {root, file_count, total_size, files: [{rel_path, size, mtime,
    hash, mime}, ...], errors: [...]}.
    """
    root = Path(root_path).resolve()
    if not root.exists():
        return {"error": f"Path non esiste: {root_path}", "files": []}
    if not root.is_dir():
        return {"error": "Path non è una directory", "files": []}
    patterns = set(skip_patterns or DEFAULT_SKIP)
    files = []
    total = 0
    errors = []
    base_depth = len(root.parts)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        # Skip ignored dirs
        dirnames[:] = [d for d in dirnames if not _should_skip(d, patterns)]
        for fn in filenames:
            if _should_skip(fn, patterns):
                continue
            if count >= max_files:
                errors.append(f"Max files {max_files} raggiunto, troncato")
                return _finalize(root, files, total, errors)
            fp = Path(dirpath) / fn
            try:
                st = fp.stat()
            except OSError as e:
                errors.append(f"{fp}: {e}")
                continue
            rel = str(fp.relative_to(root)).replace("\\", "/")
            mime, _ = mimetypes.guess_type(fn)
            entry = {
                "rel_path": rel,
                "filename": fn,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "mime": mime or "application/octet-stream",
                "hash": None,
                "hash_algo": "xxh64" if _HAS_XXHASH else "md5",
            }
            if compute_checksum:
                entry["hash"] = _hash_file(fp)
            files.append(entry)
            total += st.st_size
            count += 1
    return _finalize(root, files, total, errors)


def _finalize(root: Path, files, total, errors) -> dict:
    return {
        "root": str(root),
        "file_count": len(files),
        "total_size": total,
        "files": files,
        "errors": errors,
        "algo": "xxh64" if _HAS_XXHASH else "md5",
    }
