"""
MediaFlow — Context helpers.

v3.5.0-alpha.101 — Multi-tenant HARD R-MT1: il tenant del contesto corrente
deriva da `contextvars.ContextVar` popolata dal middleware tenant_resolver
ad ogni request. Fallback `DEFAULT_TENANT_ID=1` per servizi background /
script CLI (no request context).

Resolution chain nel middleware:
  1. Subdomain del host (es. `acme.mediaflow.it` → slug "acme" → tenant.id)
  2. Header X-Tenant-Slug (dev/test)
  3. Query param ?tenant=X (dev/test)
  4. JWT.tid (se utente loggato)
  5. DEFAULT_TENANT_ID (fallback dev mode + script)

Cross-tenant safety: se l'utente JWT.tid != request-resolved tenant_id,
middleware ritorna 403 (utente sta provando ad accedere a tenant non suo).
"""
from __future__ import annotations

import contextvars
from typing import Optional


DEFAULT_TENANT_ID: int = 1

# ContextVar settata dal middleware tenant_resolver. None se la request
# non passa per il middleware (script CLI, test unitari isolati).
_TENANT_CTX: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "mediaflow_tenant_id", default=None,
)


def set_tenant_id(tid: int) -> contextvars.Token:
    """Set tenant_id corrente. Ritorna Token per reset()."""
    return _TENANT_CTX.set(tid)


def reset_tenant_id(token: contextvars.Token) -> None:
    _TENANT_CTX.reset(token)


def current_tenant_id() -> int:
    """Ritorna tenant_id corrente. Fallback DEFAULT_TENANT_ID se ctx vuoto."""
    val = _TENANT_CTX.get()
    return val if val is not None else DEFAULT_TENANT_ID


def get_tenant_id() -> int:
    """FastAPI dependency: `tenant_id: int = Depends(get_tenant_id)`."""
    return current_tenant_id()


def get_optional_tenant_id() -> Optional[int]:
    """Variante non-bloccante: ritorna None se ctx vuoto (no fallback)."""
    return _TENANT_CTX.get()
