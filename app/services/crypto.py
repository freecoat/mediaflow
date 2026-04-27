"""
MediaFlow — cifratura simmetrica per segreti applicativi (api_key AI provider).

Usa cryptography.fernet con chiave dedicata `AI_KEY_ENCRYPTION_KEY` in .env.
Separata da SECRET_KEY (JWT) per evitare che la rotazione di una invalidi l'altra.
"""
from __future__ import annotations
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)


_fernet: Optional[Fernet] = None


def _derive_key(raw: str) -> bytes:
    """
    Accetta sia chiavi Fernet già base64-urlsafe valide (44 char) sia stringhe
    arbitrarie: in quest'ultimo caso applica SHA-256 per ottenere 32 byte e
    li codifica base64-urlsafe.
    """
    if not raw:
        raise RuntimeError("AI_KEY_ENCRYPTION_KEY mancante in .env")
    # se la stringa è già una Fernet key valida la usiamo direttamente
    try:
        if len(raw) == 44 and raw.endswith("="):
            base64.urlsafe_b64decode(raw.encode())
            return raw.encode()
    except Exception:
        pass
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = _derive_key(settings.ai_key_encryption_key or "")
        _fernet = Fernet(key)
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """Cifra una stringa. Restituisce token testuale (UTF-8)."""
    if plaintext is None:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> Optional[str]:
    """Decifra un token. Ritorna None se non valido (chiave ruotata o token corrotto)."""
    if not token:
        return None
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Token cifrato non valido (chiave AI_KEY_ENCRYPTION_KEY cambiata?)")
        return None


def generate_key() -> str:
    """Genera una nuova chiave Fernet pronta per .env."""
    return Fernet.generate_key().decode("utf-8")
