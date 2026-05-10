"""
MediaFlow — Context helpers (v3.5.0-alpha.66.15.1)

Single source of truth per il "tenant scope corrente" + helpers di contesto
condiviso tra router e services. Pattern dependency-injection FastAPI con
default deterministico per la modalità single-tenant attuale.

USO:

    from fastapi import Depends
    from app.context import get_tenant_id

    @router.get("/api/items")
    def list_items(
        tenant_id: int = Depends(get_tenant_id),
        db: Session = Depends(get_db),
    ):
        return db.query(Item).filter(Item.tenant_id == tenant_id).all()

In service layer (no FastAPI):

    from app.context import current_tenant_id
    n = db.query(Foo).filter(Foo.tenant_id == current_tenant_id()).count()

Quando arriverà multi-tenant hard (Fase 7), basterà cambiare `get_tenant_id`
e `current_tenant_id` per derivare il tenant dal token JWT / hostname /
sottodominio. Tutti i call site che usano questa API sono già pronti.

NB: durante la migrazione R1.2, i router useranno PROGRESSIVAMENTE
`Depends(get_tenant_id)` al posto della costante locale `CURRENT_TENANT = 1`.
Per il sprint R1.1 esiste solo lo stub: il valore restituito è SEMPRE 1.
"""
from __future__ import annotations

from typing import Optional


# Costante esposta come fallback per call site non-FastAPI (services). In
# Fase 7 sarà sostituita da uno store contesto-locale (contextvars) popolato
# all'inizio di ogni request via middleware.
DEFAULT_TENANT_ID: int = 1


def current_tenant_id() -> int:
    """Ritorna il tenant_id del contesto corrente.

    Stub R1.1: ritorna sempre `DEFAULT_TENANT_ID = 1`. In Fase 7 leggerà
    da `contextvars.ContextVar` popolata dal middleware auth.
    """
    return DEFAULT_TENANT_ID


def get_tenant_id() -> int:
    """FastAPI dependency: `tenant_id: int = Depends(get_tenant_id)`.

    Stub R1.1: ritorna sempre `DEFAULT_TENANT_ID = 1`. Quando R1 sarà
    completato, deriverà il valore dall'utente loggato (`request.state.
    current_user.tenant_id`) con fallback `DEFAULT_TENANT_ID` per la
    modalità demo single-user.
    """
    return DEFAULT_TENANT_ID


def get_optional_tenant_id() -> Optional[int]:
    """Variante non-bloccante: ritorna None se non c'è contesto tenant
    determinabile. Per ora si comporta come `get_tenant_id` (stub).
    Utile in endpoint pubblici (es. /tech-sheet/{token}) che non vogliono
    il tenant scope obbligato.
    """
    return DEFAULT_TENANT_ID
