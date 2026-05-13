"""v3.5.0-alpha.110 — Storage backend interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Iterator


class StorageError(Exception):
    """Errore generico storage (network, auth, not found)."""


@dataclass
class FileInfo:
    key: str
    size: int
    mtime: Optional[float] = None
    etag: Optional[str] = None
    content_type: Optional[str] = None


class StorageBackend(ABC):
    """Interface storage. Implementazioni: LocalFS, S3 (boto3 compatible)."""

    name: str = "base"

    @abstractmethod
    def upload(self, key: str, data: bytes, content_type: Optional[str] = None) -> FileInfo:
        ...

    @abstractmethod
    def download(self, key: str) -> bytes:
        ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def stat(self, key: str) -> Optional[FileInfo]:
        ...

    @abstractmethod
    def list(self, prefix: str = "", limit: int = 1000) -> Iterator[FileInfo]:
        ...

    @abstractmethod
    def presigned_url(self, key: str, expires: int = 3600) -> Optional[str]:
        ...

    @abstractmethod
    def resolve_path(self, key: str) -> str:
        ...
