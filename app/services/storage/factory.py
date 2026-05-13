"""v3.5.0-alpha.110 — Factory per ottenere il backend storage giusto.

Routing:
- Project.storage_backend = 'local' o vuoto → LocalFS con storage_root
  (default uploads/t{tid}/p{pid}/)
- Project.storage_backend = 's3' / 's3_*' → S3Backend con bucket Project.s3_bucket
  + credenziali ENV
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional

from app.config import settings
from .base import StorageBackend, StorageError
from .local_fs import LocalFSBackend


def _is_s3_backend(name: Optional[str]) -> bool:
    return bool(name) and name.lower().startswith("s3")


def get_storage_for_tenant(tenant_id: int) -> StorageBackend:
    """Storage tenant-level: uploads/t{tid}/. Sempre LocalFS (non per-project)."""
    root = Path(settings.upload_dir) / f"t{tenant_id}"
    return LocalFSBackend(root)


def get_storage_for_project(project, fallback_tenant_id: Optional[int] = None) -> StorageBackend:
    """Storage per progetto. Se Project ha storage_backend specifico → usa quello.
    Altrimenti fallback a tenant-level LocalFS.
    """
    backend_name = getattr(project, "storage_backend", None) if project else None
    tid = getattr(project, "tenant_id", None) if project else fallback_tenant_id
    if tid is None:
        tid = 1
    if _is_s3_backend(backend_name):
        from .s3 import S3Backend
        bucket = getattr(project, "s3_bucket", None) or settings.aws_s3_default_bucket
        if not bucket:
            raise StorageError(
                f"Project {getattr(project, 'id', '?')}.storage_backend={backend_name} "
                "ma s3_bucket vuoto e AWS_S3_DEFAULT_BUCKET non configurato in ENV"
            )
        if not settings.aws_access_key_id or not settings.aws_secret_access_key:
            raise StorageError(
                "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY mancanti in ENV. "
                "Imposta in .env per attivare storage S3."
            )
        prefix = (getattr(project, "storage_root", None) or f"t{tid}/p{project.id}/").strip("/")
        return S3Backend(
            bucket=bucket,
            prefix=prefix,
            endpoint_url=settings.aws_s3_endpoint,
            region=settings.aws_s3_region,
            access_key=settings.aws_access_key_id,
            secret_key=settings.aws_secret_access_key,
            use_ssl=settings.aws_s3_use_ssl,
            presigned_ttl=settings.aws_s3_presigned_ttl,
        )
    # Local: per-project se storage_root settato, altrimenti tenant root
    if project and getattr(project, "storage_root", None):
        return LocalFSBackend(getattr(project, "storage_root"))
    base = Path(settings.upload_dir) / f"t{tid}"
    if project and getattr(project, "id", None):
        base = base / f"p{project.id}"
    return LocalFSBackend(base)
