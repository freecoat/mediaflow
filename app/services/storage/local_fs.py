"""v3.5.0-alpha.110 — Storage backend filesystem locale."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Optional, Iterator
import mimetypes

from .base import StorageBackend, FileInfo, StorageError


class LocalFSBackend(StorageBackend):
    """Backend filesystem locale. Base: uno specifico Path root.

    Tipici roots:
    - uploads/t{tenant_id}/p{project_id}/  (per-project)
    - uploads/t{tenant_id}/                 (per-tenant fallback)
    - uploads/                              (legacy, accessibile per back-compat)
    """

    name = "local"

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _full(self, key: str) -> Path:
        # Path traversal guard: key resolved deve essere sotto root
        target = (self.root / key).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise StorageError(f"path traversal rifiutato: {key}")
        return target

    def upload(self, key: str, data: bytes, content_type: Optional[str] = None) -> FileInfo:
        full = self._full(key)
        full.parent.mkdir(parents=True, exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        return FileInfo(key=key, size=len(data), content_type=content_type)

    def download(self, key: str) -> bytes:
        full = self._full(key)
        if not full.exists():
            raise StorageError(f"key non trovata: {key}")
        return full.read_bytes()

    def delete(self, key: str) -> bool:
        full = self._full(key)
        if not full.exists():
            return False
        full.unlink()
        return True

    def exists(self, key: str) -> bool:
        return self._full(key).exists()

    def stat(self, key: str) -> Optional[FileInfo]:
        full = self._full(key)
        if not full.exists():
            return None
        st = full.stat()
        mime, _ = mimetypes.guess_type(full.name)
        return FileInfo(
            key=key, size=st.st_size, mtime=st.st_mtime,
            content_type=mime,
        )

    def list(self, prefix: str = "", limit: int = 1000) -> Iterator[FileInfo]:
        base = self._full(prefix) if prefix else self.root
        if not base.exists():
            return
        count = 0
        for fp in base.rglob("*"):
            if not fp.is_file():
                continue
            if count >= limit:
                return
            rel = fp.relative_to(self.root).as_posix()
            st = fp.stat()
            mime, _ = mimetypes.guess_type(fp.name)
            yield FileInfo(key=rel, size=st.st_size, mtime=st.st_mtime, content_type=mime)
            count += 1

    def presigned_url(self, key: str, expires: int = 3600) -> Optional[str]:
        # Per local FS non c'è presigned. Il caller usa /dam/download/{asset_id}.
        return None

    def resolve_path(self, key: str) -> str:
        return str(self._full(key))
