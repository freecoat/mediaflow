"""v3.5.0-alpha.70.4 — MFA TOTP service.

pyotp + qrcode. Secret Fernet-encrypted in DB con AI_KEY_ENCRYPTION_KEY
(riuso per non aggiungere env var nuova).

Flow:
  1. setup_secret(user) → ritorna (plain_secret, qr_png_bytes,
     provisioning_uri). Salva secret_encrypted ma mfa_enabled resta False.
  2. user scansiona QR su Google Auth / Authy / etc.
  3. verify_setup(user, code) → verifica primo OTP. Se valido →
     mfa_enabled=True, mfa_enabled_at=now.
  4. Login flow: dopo password OK, se user.mfa_enabled → richiedi OTP.
  5. disable_mfa(user, code) → richiede OTP per confermare.
"""
from __future__ import annotations
from app.services.clock import now_utc
import io
from datetime import datetime
from typing import Optional, Tuple

import pyotp
import qrcode

from app.services.crypto import encrypt_secret, decrypt_secret


ISSUER = "Claqo"


def generate_secret() -> str:
    """Nuovo secret base32 (160 bit standard)."""
    return pyotp.random_base32()


def get_provisioning_uri(secret: str, user_email: str) -> str:
    """URI otpauth:// per QR code."""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=user_email, issuer_name=ISSUER
    )


def generate_qr_png(uri: str) -> bytes:
    """PNG bytes per QR code dell'URI."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify_otp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Verifica OTP. valid_window=1 accetta anche il code precedente (drift)."""
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def setup_user_mfa(user) -> Tuple[str, bytes, str]:
    """Genera secret + QR + URI. Salva secret_encrypted sull'user (caller
    fa commit). NON setta mfa_enabled — serve verify_setup riuscito.
    Ritorna (plain_secret, qr_png_bytes, provisioning_uri)."""
    secret = generate_secret()
    user.mfa_secret_encrypted = encrypt_secret(secret)
    user.mfa_enabled = False
    uri = get_provisioning_uri(secret, user.email)
    png = generate_qr_png(uri)
    return secret, png, uri


def decrypt_user_secret(user) -> Optional[str]:
    """Decifra il secret dell'user. None se non configurato."""
    if not user.mfa_secret_encrypted:
        return None
    return decrypt_secret(user.mfa_secret_encrypted)


def verify_user_otp(user, code: str) -> bool:
    """Verifica OTP per user con secret salvato."""
    secret = decrypt_user_secret(user)
    if not secret:
        return False
    return verify_otp(secret, code)


def confirm_setup(user, code: str) -> bool:
    """Verify primo OTP dopo setup. Se OK enables MFA."""
    if verify_user_otp(user, code):
        user.mfa_enabled = True
        user.mfa_enabled_at = now_utc()
        return True
    return False


def disable_mfa(user, code: str) -> bool:
    """Disable richiede OTP attivo. Se OK clears secret + flag."""
    if not user.mfa_enabled:
        return True
    if not verify_user_otp(user, code):
        return False
    user.mfa_secret_encrypted = None
    user.mfa_enabled = False
    user.mfa_enabled_at = None
    return True
