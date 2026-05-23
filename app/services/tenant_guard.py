"""Tenant scope guard centralizzato (Sprint 1 — v3.5.0-alpha.172.35).

Chiude la classe di bug "cross-tenant data leak" su pattern by-ID lookup e
page-render. Sostituisce il pattern manuale `db.query(Model).filter(Model.id == x).first()`
con un helper che applica automaticamente lo scope al tenant corrente.

Convenzioni MediaFlow:
- ogni Model di business ha colonna diretta `tenant_id`
- eccezione: Invoice/InvoiceLine — non hanno tenant_id, scope via Client.tenant_id
  (vedi `_INDIRECT_VIA_CLIENT`). InvoicePayment invece HA tenant_id diretto.
- helper sollevano 404 se record non trovato OR fuori scope (no enumeration attack)
- helper falliscono LOUD se Model nuovo non ha strategia definita (no leak silente)

Uso:
    from app.services.tenant_guard import scoped, fetch_or_404, fetch_invoice_or_404

    # filtro su query esistente
    jobs = scoped(db.query(Job).options(...), Job).order_by(...).all()

    # by-ID con 404 + scope automatico
    job = fetch_or_404(db, Job, job_id, error="Job non trovato")

    # Invoice (scope indiretto via Client)
    inv = fetch_invoice_or_404(db, invoice_id)
"""
from __future__ import annotations
from typing import Type, TypeVar

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.context import current_tenant_id
from app.models import Invoice, Client

T = TypeVar("T")

# Modelli senza colonna `tenant_id` diretta — scope via JOIN su Client.
# Estendere quando se ne aggiungono altri (es. InvoiceLine se usata by-ID).
_INDIRECT_VIA_CLIENT = {Invoice}


def scoped(query, model: Type[T]):
    """Applica filtro tenant_id al query passato.

    Riconosce indirezione via Client per i modelli in `_INDIRECT_VIA_CLIENT`.
    Solleva RuntimeError se il Model non ha strategia di scope (forza il
    chiamante a dichiararne una invece di silenziosamente leakare).
    """
    if model in _INDIRECT_VIA_CLIENT:
        return query.join(Client, model.client_id == Client.id).filter(
            Client.tenant_id == current_tenant_id()
        )
    mapper = inspect(model)
    if "tenant_id" in mapper.columns:
        return query.filter(model.tenant_id == current_tenant_id())
    raise RuntimeError(
        f"tenant_guard: {model.__name__} non ha strategia di scope. "
        f"Aggiungi colonna `tenant_id` al model o registra il modello in "
        f"`_INDIRECT_VIA_CLIENT` con regola di JOIN dedicata."
    )


def fetch_or_404(
    db: Session,
    model: Type[T],
    obj_id: int,
    *,
    error: str = "Risorsa non trovata",
) -> T:
    """Generic by-ID fetch con tenant guard. Solleva 404 se id sconosciuto
    OR record di altro tenant (no enumeration leak: stesso codice 404 in
    entrambi i casi).
    """
    obj = scoped(db.query(model), model).filter(model.id == obj_id).first()
    if not obj:
        raise HTTPException(404, error)
    return obj


def fetch_invoice_or_404(
    db: Session,
    invoice_id: int,
    *,
    error: str = "Fattura non trovata",
) -> Invoice:
    """Specializzato per Invoice — scope via Client. Equivalente a
    `fetch_or_404(db, Invoice, invoice_id)` ma con messaggio default IT.
    """
    return fetch_or_404(db, Invoice, invoice_id, error=error)
