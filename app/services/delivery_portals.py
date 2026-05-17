"""Delivery portals plugin architecture — v3.5.0-alpha.155.

Architettura plugin: ogni broadcaster ha un modulo provider in `_PROVIDERS`
con metodi (upload_file, list_uploads, validate_auth). Plugin key registrato
in DeliveryPortal.plugin_key.

Plugin built-in:
- generic_http: HTTP POST multipart con bearer token (default fallback)
- manual: NO-OP, MediaFlow traccia solo lo stato

Plugin futuri (TODO):
- netflix_aspera: Aspera fasp protocol
- amazon_s3: AWS S3 + signed URLs
- sky_signiant: Signiant Media Shuttle
- a24_box: Box.com API

Auth config Fernet-cifrato via AI_KEY_ENCRYPTION_KEY (riuso α.137).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.models import DeliveryPortal, DeliveryUpload, DeliveryUploadStatus

log = logging.getLogger(__name__)


# ── Fernet encryption (riuso AI_KEY_ENCRYPTION_KEY) ───────────────────

def _fernet() -> Optional[Fernet]:
    key = os.getenv("AI_KEY_ENCRYPTION_KEY")
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def encrypt_auth_config(config: dict) -> str:
    if not config:
        return ""
    raw = json.dumps(config)
    f = _fernet()
    if not f:
        log.warning("AI_KEY_ENCRYPTION_KEY mancante — auth_config NON cifrato")
        return raw
    return f.encrypt(raw.encode()).decode()


def decrypt_auth_config(enc: str) -> Optional[dict]:
    if not enc:
        return None
    f = _fernet()
    if not f:
        try:
            return json.loads(enc)  # fallback non cifrato
        except json.JSONDecodeError:
            return None
    try:
        return json.loads(f.decrypt(enc.encode()).decode())
    except InvalidToken:
        log.error("decrypt_auth_config: InvalidToken")
        return None
    except json.JSONDecodeError:
        return None


# ── Plugin interface ─────────────────────────────────────────────────

class DeliveryPortalPlugin:
    """Base plugin. Override metodi in sottoclassi specifiche broadcaster."""
    key: str = "base"
    label: str = "Base"

    def validate_auth(self, auth_config: dict) -> tuple[bool, str]:
        """Verifica credenziali. Ritorna (ok, message)."""
        return True, "ok"

    def upload_file(
        self, portal: DeliveryPortal, file_path: str, *, metadata: Optional[dict] = None,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Upload file. Ritorna (success, remote_url, error_message)."""
        raise NotImplementedError("subclass must implement upload_file")


class ManualPortalPlugin(DeliveryPortalPlugin):
    """Plugin per portali manuali (UI esterna). No-op upload — MediaFlow
    traccia solo lo stato registrato dall'utente."""
    key = "manual"
    label = "Manuale (tracking solo)"

    def validate_auth(self, auth_config):
        return True, "ok (no auth required)"

    def upload_file(self, portal, file_path, *, metadata=None):
        return True, None, "Manual portal: upload eseguito esternamente, MediaFlow registra solo lo stato"


class GenericHttpPortalPlugin(DeliveryPortalPlugin):
    """HTTP POST multipart con bearer token. Auth config:
    {"endpoint": "https://...", "token": "..."}.
    """
    key = "generic_http"
    label = "HTTP generico (POST multipart + bearer token)"

    def validate_auth(self, auth_config):
        if not isinstance(auth_config, dict):
            return False, "auth_config deve essere dict"
        if not auth_config.get("token"):
            return False, "token mancante"
        return True, "ok"

    def upload_file(self, portal, file_path, *, metadata=None):
        import urllib.request
        auth = decrypt_auth_config(portal.auth_config_enc or "")
        if not auth:
            return False, None, "auth_config decrypt failed"
        endpoint = auth.get("endpoint") or portal.base_url
        token = auth.get("token")
        if not endpoint or not token:
            return False, None, "endpoint o token mancante"
        try:
            with open(file_path, "rb") as f:
                data = f.read()
            req = urllib.request.Request(endpoint, data=data, method="POST", headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            })
            with urllib.request.urlopen(req, timeout=300) as r:
                if 200 <= r.status < 300:
                    body = r.read().decode(errors="replace")[:500]
                    return True, body, None
                return False, None, f"HTTP {r.status}: {r.read().decode(errors='replace')[:200]}"
        except Exception as e:
            return False, None, f"upload error: {e}"


_PROVIDERS = {
    "manual": ManualPortalPlugin(),
    "generic_http": GenericHttpPortalPlugin(),
    # Futuri broadcaster-specific: netflix_aspera, amazon_s3, sky_signiant, a24_box
}


def get_plugin(plugin_key: str) -> DeliveryPortalPlugin:
    return _PROVIDERS.get(plugin_key, _PROVIDERS["manual"])


def list_plugin_keys() -> list[dict]:
    return [{"key": p.key, "label": p.label} for p in _PROVIDERS.values()]


def execute_upload(
    db: Session, upload: DeliveryUpload,
) -> DeliveryUpload:
    """Esegue upload via plugin del portale. Aggiorna status + error_message.
    Fail-soft: catch generico, status=failed con error_message. Idempotente:
    se status già done/failed, no-op."""
    from datetime import datetime
    if upload.status in (DeliveryUploadStatus.done, DeliveryUploadStatus.cancelled):
        return upload
    if not upload.file_path:
        upload.status = DeliveryUploadStatus.failed
        upload.error_message = "file_path mancante"
        upload.completed_at = datetime.utcnow()
        db.commit()
        return upload
    portal = db.query(DeliveryPortal).filter(DeliveryPortal.id == upload.portal_id).first()
    if not portal:
        upload.status = DeliveryUploadStatus.failed
        upload.error_message = "portale non trovato"
        upload.completed_at = datetime.utcnow()
        db.commit()
        return upload
    plugin = get_plugin(portal.plugin_key)
    upload.status = DeliveryUploadStatus.uploading
    db.commit()
    try:
        ok, remote_url, err = plugin.upload_file(portal, upload.file_path)
        if ok:
            upload.status = DeliveryUploadStatus.done
            upload.upload_url = remote_url
            upload.progress_pct = 100.0
            upload.completed_at = datetime.utcnow()
        else:
            upload.status = DeliveryUploadStatus.failed
            upload.error_message = err or "upload failed senza dettagli"
            upload.completed_at = datetime.utcnow()
    except Exception as e:
        upload.status = DeliveryUploadStatus.failed
        upload.error_message = f"plugin exception: {e}"
        upload.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(upload)
    return upload
