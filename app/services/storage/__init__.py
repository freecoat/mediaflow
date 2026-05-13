"""v3.5.0-alpha.110 — Storage adapter pattern (S3-compatible + local FS).

Storage backend astratto per Asset DAM. Routing per-progetto:
- Project.storage_backend = local | s3 | s3_minio | s3_r2 | s3_wasabi
- Project.storage_root = path/prefix dedicato
- Project.s3_bucket = bucket S3 (se backend s3*)

Credenziali AWS via ENV (no DB) per sicurezza.

Pattern uso:
    from app.services.storage import get_storage_for_project
    storage = get_storage_for_project(project)
    storage.upload(file_bytes, "assets/photo.jpg")
    url = storage.presigned_url("assets/photo.jpg", expires=3600)
"""
from .base import StorageBackend, StorageError, FileInfo
from .factory import get_storage_for_project, get_storage_for_tenant

__all__ = [
    "StorageBackend", "StorageError", "FileInfo",
    "get_storage_for_project", "get_storage_for_tenant",
]
