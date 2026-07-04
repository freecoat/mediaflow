"""OAuth 2 Authorization Code flow — v3.5.0-alpha.152.

Provider supportati:
- google (Gmail + Drive + Calendar)
- microsoft (Outlook + OneDrive)

Env vars necessarie (`.env`):
- GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET
- MICROSOFT_OAUTH_CLIENT_ID / MICROSOFT_OAUTH_CLIENT_SECRET
- OAUTH_REDIRECT_BASE_URL (default http://localhost:8000)

Scope di default:
- google: openid email profile https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/calendar.app.created https://www.googleapis.com/auth/calendar.readonly
- microsoft: openid email profile offline_access User.Read Mail.Send Files.ReadWrite

Refresh token: cifrato via Fernet AI_KEY_ENCRYPTION_KEY (riuso α.137).
"""
from __future__ import annotations
from app.services.clock import now_utc

import base64
import hashlib
import hmac
import os
import json
import logging
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import settings
from app.models import UserOAuthToken

log = logging.getLogger(__name__)


# ── Provider definitions ──────────────────────────────────────────────

PROVIDERS = {
    "google": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scopes": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.send "
            "https://www.googleapis.com/auth/drive.file "
            "https://www.googleapis.com/auth/calendar.app.created "
            "https://www.googleapis.com/auth/calendar.readonly"
        ),
        "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
        "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
        "label": "Google (Calendar + Drive)",
    },
    "microsoft": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "scopes": (
            "openid email profile offline_access "
            "User.Read Mail.Send Files.ReadWrite"
        ),
        "client_id_env": "MICROSOFT_OAUTH_CLIENT_ID",
        "client_secret_env": "MICROSOFT_OAUTH_CLIENT_SECRET",
        "label": "Microsoft (Outlook + OneDrive)",
    },
}


def _redirect_base_url() -> str:
    return os.getenv("OAUTH_REDIRECT_BASE_URL", "http://localhost:8000").rstrip("/")


def redirect_uri(provider: str) -> str:
    return f"{_redirect_base_url()}/auth/oauth/{provider}/callback"


def _state_secret() -> bytes:
    return (settings.secret_key or "").encode()


def make_oauth_state(user_id: int, provider: str, ttl_seconds: int = 600) -> str:
    """State CSRF firmato HMAC, stateless. Formato: b64url(payload).hexsig"""
    exp = int(now_utc().timestamp()) + ttl_seconds
    payload = json.dumps({"u": user_id, "p": provider, "e": exp}, separators=(",", ":")).encode()
    b64 = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    sig = hmac.new(_state_secret(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def verify_oauth_state(state: str) -> Optional[dict]:
    """Verifica firma + scadenza. Ritorna {'user_id','provider'} o None."""
    if not state or "." not in state:
        return None
    b64, _, sig = state.partition(".")
    expected = hmac.new(_state_secret(), b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        padded = b64 + "=" * (-len(b64) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception:
        return None
    if int(data.get("e", 0)) < int(now_utc().timestamp()):
        return None
    uid = data.get("u")
    prov = data.get("p")
    if uid is None or prov is None:
        return None
    return {"user_id": uid, "provider": prov}


def is_configured(provider: str) -> bool:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return False
    cid = os.getenv(cfg["client_id_env"]) or ""
    csec = os.getenv(cfg["client_secret_env"]) or ""
    return bool(cid.strip()) and bool(csec.strip())


def authorization_url(provider: str, state: str) -> str:
    """Costruisce URL di autorizzazione del provider."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Provider OAuth sconosciuto: {provider}")
    params = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": cfg["scopes"],
        "state": state,
        "access_type": "offline",      # Google: forza refresh_token
        "prompt": "consent",            # Forza re-consent per ottenere refresh_token
    }
    return cfg["auth_url"] + "?" + urllib.parse.urlencode(params)


def _http_post(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def _http_get_json(url: str, access_token: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def exchange_code_for_token(provider: str, code: str) -> dict:
    """Scambia authorization code per access+refresh token."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Provider sconosciuto: {provider}")
    data = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "client_secret": os.getenv(cfg["client_secret_env"], ""),
        "code": code,
        "redirect_uri": redirect_uri(provider),
        "grant_type": "authorization_code",
    }
    return _http_post(cfg["token_url"], data)


def fetch_userinfo(provider: str, access_token: str) -> dict:
    """Recupera info utente dal provider per identificare account collegato."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Provider sconosciuto: {provider}")
    return _http_get_json(cfg["userinfo_url"], access_token)


# ── Refresh token encryption (Fernet, riuso AI_KEY_ENCRYPTION_KEY) ──

def _fernet() -> Optional[Fernet]:
    key = os.getenv("AI_KEY_ENCRYPTION_KEY")
    if not key:
        log.warning("AI_KEY_ENCRYPTION_KEY non impostata — refresh_token non sarà cifrato")
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        log.error(f"Fernet init failed: {e}")
        return None


def encrypt_refresh_token(rt: str) -> str:
    if not rt:
        return ""
    f = _fernet()
    if not f:
        return rt  # fallback in chiaro (warning sopra)
    return f.encrypt(rt.encode()).decode()


def decrypt_refresh_token(enc: str) -> Optional[str]:
    if not enc:
        return None
    f = _fernet()
    if not f:
        return enc
    try:
        return f.decrypt(enc.encode()).decode()
    except InvalidToken:
        log.error("decrypt_refresh_token: InvalidToken (key cambiata?)")
        return None


# ── DB helpers ────────────────────────────────────────────────────────

def save_token(db: Session, user_id: int, provider: str, token_response: dict,
               account_email: Optional[str] = None) -> UserOAuthToken:
    """Upsert UserOAuthToken con il token response del provider."""
    access = token_response.get("access_token")
    refresh = token_response.get("refresh_token")  # opzionale
    expires_in = token_response.get("expires_in", 3600)
    scope = token_response.get("scope")
    expires_at = now_utc() + timedelta(seconds=int(expires_in))

    existing = db.query(UserOAuthToken).filter(
        UserOAuthToken.user_id == user_id,
        UserOAuthToken.provider == provider,
    ).first()
    if existing:
        existing.access_token = access
        # Refresh: aggiorna solo se nuovo (alcuni provider non lo ri-emettono)
        if refresh:
            existing.refresh_token_enc = encrypt_refresh_token(refresh)
        existing.expires_at = expires_at
        existing.scopes = scope
        if account_email:
            existing.account_email = account_email
        existing.updated_at = now_utc()
        return existing
    row = UserOAuthToken(
        user_id=user_id, provider=provider,
        access_token=access,
        refresh_token_enc=encrypt_refresh_token(refresh) if refresh else None,
        expires_at=expires_at,
        scopes=scope,
        account_email=account_email,
    )
    db.add(row)
    return row


def get_token(db: Session, user_id: int, provider: str) -> Optional[UserOAuthToken]:
    return db.query(UserOAuthToken).filter(
        UserOAuthToken.user_id == user_id,
        UserOAuthToken.provider == provider,
    ).first()


def revoke_token(db: Session, user_id: int, provider: str) -> bool:
    row = get_token(db, user_id, provider)
    if not row:
        return False
    db.delete(row)
    return True


def list_tokens(db: Session, user_id: int) -> list[UserOAuthToken]:
    return db.query(UserOAuthToken).filter(UserOAuthToken.user_id == user_id).all()


# ── Refresh automatico access token ──────────────────────────────────

_REFRESH_SKEW_SECONDS = 120


def refresh_access_token(provider: str, refresh_token: str) -> dict:
    """Rinnova l'access token usando il refresh token. Ritorna il token response."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise ValueError(f"Provider sconosciuto: {provider}")
    data = {
        "client_id": os.getenv(cfg["client_id_env"], ""),
        "client_secret": os.getenv(cfg["client_secret_env"], ""),
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    return _http_post(cfg["token_url"], data)


def get_valid_access_token(db: Session, user_id: int, provider: str) -> Optional[str]:
    """Ritorna un access token valido, rinnovandolo se scaduto/in scadenza.

    Aggiorna la riga token in DB (access_token, expires_at) SENZA commit:
    il chiamante è responsabile del commit. Ritorna None se non collegato
    o se il refresh fallisce.
    """
    row = get_token(db, user_id, provider)
    if not row or not row.access_token:
        return None
    # token ancora valido oltre la soglia di skew?
    if row.expires_at and row.expires_at > now_utc() + timedelta(seconds=_REFRESH_SKEW_SECONDS):
        return row.access_token
    # serve refresh
    rt = decrypt_refresh_token(row.refresh_token_enc) if row.refresh_token_enc else None
    if not rt:
        log.warning(f"get_valid_access_token: nessun refresh_token per user {user_id}/{provider}")
        return row.access_token  # best effort: potrebbe essere ancora valido
    try:
        resp = refresh_access_token(provider, rt)
    except Exception as e:
        log.error(f"refresh_access_token failed user {user_id}/{provider}: {e}")
        return None
    new_access = resp.get("access_token")
    if not new_access:
        log.error(f"refresh_access_token: risposta senza access_token user {user_id}/{provider}")
        return None
    row.access_token = new_access
    row.expires_at = now_utc() + timedelta(seconds=int(resp.get("expires_in", 3600)))
    if resp.get("refresh_token"):  # Google talvolta ri-emette
        row.refresh_token_enc = encrypt_refresh_token(resp["refresh_token"])
    row.updated_at = now_utc()
    return new_access
