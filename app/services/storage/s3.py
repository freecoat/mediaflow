"""v3.5.0-alpha.110 — Storage backend S3-compatible (AWS S3, MinIO, R2, Wasabi).

Credenziali da ENV (config.py): AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_S3_ENDPOINT (vuoto = AWS standard), AWS_S3_REGION.
"""
from __future__ import annotations
from typing import Optional, Iterator
import logging

from .base import StorageBackend, FileInfo, StorageError

logger = logging.getLogger(__name__)


class S3Backend(StorageBackend):
    """Backend S3-compatible via boto3."""

    name = "s3"

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: Optional[str] = None,
        region: str = "eu-west-1",
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        use_ssl: bool = True,
        presigned_ttl: int = 3600,
    ):
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise StorageError("boto3 non installato. `pip install boto3`")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.presigned_ttl = presigned_ttl
        self._client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            endpoint_url=endpoint_url or None,
            region_name=region,
            use_ssl=use_ssl,
            config=Config(signature_version="s3v4"),
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key}".lstrip("/") if self.prefix else key

    def upload(self, key: str, data: bytes, content_type: Optional[str] = None) -> FileInfo:
        s3_key = self._key(key)
        extra = {"ContentType": content_type} if content_type else {}
        try:
            self._client.put_object(Bucket=self.bucket, Key=s3_key, Body=data, **extra)
        except Exception as e:
            raise StorageError(f"upload S3 fallito: {e}")
        return FileInfo(key=key, size=len(data), content_type=content_type)

    def download(self, key: str) -> bytes:
        s3_key = self._key(key)
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=s3_key)
            return resp["Body"].read()
        except self._client.exceptions.NoSuchKey:
            raise StorageError(f"key non trovata: {key}")
        except Exception as e:
            raise StorageError(f"download S3 fallito: {e}")

    def delete(self, key: str) -> bool:
        s3_key = self._key(key)
        try:
            self._client.delete_object(Bucket=self.bucket, Key=s3_key)
            return True
        except Exception as e:
            logger.warning(f"delete S3 fallito {key}: {e}")
            return False

    def exists(self, key: str) -> bool:
        return self.stat(key) is not None

    def stat(self, key: str) -> Optional[FileInfo]:
        s3_key = self._key(key)
        try:
            head = self._client.head_object(Bucket=self.bucket, Key=s3_key)
            return FileInfo(
                key=key,
                size=head.get("ContentLength", 0),
                etag=head.get("ETag", "").strip('"'),
                content_type=head.get("ContentType"),
                mtime=head.get("LastModified").timestamp() if head.get("LastModified") else None,
            )
        except self._client.exceptions.ClientError:
            return None

    def list(self, prefix: str = "", limit: int = 1000) -> Iterator[FileInfo]:
        full_prefix = self._key(prefix) if prefix else self.prefix
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            count = 0
            for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []) or []:
                    if count >= limit:
                        return
                    # Strip prefix per ritornare key relativa
                    full = obj["Key"]
                    rel = full[len(self.prefix) + 1:] if self.prefix and full.startswith(self.prefix + "/") else full
                    yield FileInfo(
                        key=rel, size=obj.get("Size", 0),
                        mtime=obj["LastModified"].timestamp() if obj.get("LastModified") else None,
                        etag=obj.get("ETag", "").strip('"'),
                    )
                    count += 1
        except Exception as e:
            raise StorageError(f"list S3 fallito: {e}")

    def presigned_url(self, key: str, expires: Optional[int] = None) -> Optional[str]:
        s3_key = self._key(key)
        ttl = expires if expires is not None else self.presigned_ttl
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": s3_key},
                ExpiresIn=ttl,
            )
        except Exception as e:
            logger.warning(f"presigned URL fallito {key}: {e}")
            return None

    def resolve_path(self, key: str) -> str:
        # In Asset.file_path salviamo "s3://bucket/key" come marker
        return f"s3://{self.bucket}/{self._key(key)}"
