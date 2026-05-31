"""
MediaFlow — servizio autenticazione
JWT token (PyJWT) + bcrypt password hashing diretto.
Compatibile Python 3.11+ (incluso 3.14).
"""
from app.services.clock import now_utc
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
import jwt
from sqlalchemy.orm import Session
from app.config import settings
from app.models import User


def verify_password(plain: str, hashed: str) -> bool:
    """Verifica password con bcrypt."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_password(password: str) -> str:
    """Hash password con bcrypt (cost factor 12 di default)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crea JWT token firmato."""
    to_encode = data.copy()
    expire = now_utc() + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[dict]:
    """Decodifica e verifica JWT token."""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except jwt.PyJWTError:
        return None


def authenticate_user(
    db: Session,
    email: str,
    password: str,
    tenant_id: Optional[int] = None,
) -> Optional[User]:
    """Autentica utente con email + password.

    v3.5.0-alpha.101 — Multi-tenant: se `tenant_id` fornito, scope al
    tenant. Altrimenti usa primo match (back-compat single-tenant).
    """
    q = db.query(User).filter(User.email == email)
    if tenant_id is not None:
        q = q.filter(User.tenant_id == tenant_id)
    user = q.first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def get_current_user_from_token(db: Session, token: str) -> Optional[User]:
    """Recupera l'utente corrente dal JWT token.

    v3.5.0-alpha.101 — JWT include `tid` (tenant_id). Per back-compat
    accetta anche token vecchi senza tid (usa email globale come prima).
    """
    payload = decode_token(token)
    if not payload:
        return None
    email: str = payload.get("sub")
    if not email:
        return None
    tid = payload.get("tid")
    q = db.query(User).filter(User.email == email, User.is_active == True)
    if tid is not None:
        q = q.filter(User.tenant_id == int(tid))
    return q.first()


def resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    """Risolve l'utente corrente con politica auth_required.

    v3.5.0-alpha.66.14.2 — sostituisce le 5 copie ad-hoc `_resolve_current_user`
    sparse nei router. Comportamento:

    - Se `token` valido → ritorna User dal token.
    - Se `token` assente/invalido E `settings.auth_required=False` (DEV
      default) → fallback al primo User attivo per ID (compatibilità
      single-user demo storica).
    - Se `token` assente/invalido E `settings.auth_required=True` (PROD)
      → ritorna None. L'endpoint chiamante deve gestire (raise 401 o
      reindirizzare a /login). NIENTE fallback amministrativo.

    Per la migrazione: i router che usano questa funzione devono già
    gestire il caso `user is None` (alcuni endpoint AI/settings rinviano
    a 401, altri continuano in degraded mode). Verificare singolarmente.
    """
    if token:
        u = get_current_user_from_token(db, token)
        if u:
            return u
    if settings.auth_required:
        return None
    return db.query(User).filter(User.is_active == True).order_by(User.id).first()
