"""Estrazione best-effort di thumbprint + scadenza da un certificato PEM cinema.

Solo stdlib (ssl + hashlib). Degrada a None senza sollevare eccezioni.
Usato da kdm.py per leggere i metadati del certificato server DCP.
"""
import ssl
import hashlib
import os
import tempfile
from datetime import datetime


def parse_cert(pem_text: str) -> dict:
    """Estrae thumbprint SHA-1 (uppercase hex) e data di scadenza da un PEM.

    Args:
        pem_text: Testo del certificato in formato PEM.

    Returns:
        dict con chiavi:
          - "thumbprint": str (SHA-1 uppercase hex del DER) oppure None
          - "expires_at": datetime oppure None
        Non solleva mai eccezioni, anche su input garbage.
    """
    thumbprint = None
    expires_at = None

    # --- Thumbprint via DER round-trip ---
    try:
        der = ssl.PEM_cert_to_DER_cert(pem_text)
        thumbprint = hashlib.sha1(der).hexdigest().upper()
    except Exception:
        thumbprint = None

    # --- Scadenza best-effort via API privata ssl._ssl._test_decode_cert ---
    # Disponibile in CPython ma non garantita in tutte le build.
    # Se non disponibile o il PEM non è valido → None (accettabile).
    try:
        _decode_cert = getattr(ssl, "_ssl", None)
        if _decode_cert is not None:
            _decode_cert = getattr(_decode_cert, "_test_decode_cert", None)
        if _decode_cert is not None:
            with tempfile.NamedTemporaryFile(
                "w", suffix=".pem", delete=False
            ) as fh:
                fh.write(pem_text)
                path = fh.name
            try:
                info = _decode_cert(path)
                na = info.get("notAfter") if isinstance(info, dict) else None
                if na:
                    expires_at = datetime.strptime(na, "%b %d %H:%M:%S %Y %Z")
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except Exception:
        expires_at = None

    return {"thumbprint": thumbprint, "expires_at": expires_at}
