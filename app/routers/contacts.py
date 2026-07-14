"""
app/routers/contacts.py

Contatti multipli per cliente — sotto-risorsa di Client.
Settare is_primary=True sincronizza Client.contact_name/email/phone/role
e demote tutti gli altri primari dello stesso cliente.

feat/acquisizioni-fase1 — Task 10
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Form, Request
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.context import current_tenant_id
from app.models.models import (
    Contact, Client, ContactAcquisition, ContactProject, Acquisition, Project,
    Activity, EmailLink,
)
from app.services.rbac import requires_permission, current_user, has_permission
from app.services.tenant_guard import fetch_or_404

router = APIRouter(tags=["contacts"])
RequireView = Depends(requires_permission("view_clients"))
RequireEdit = Depends(requires_permission("edit_clients"))


def _contact_dict(c: Contact) -> dict:
    return {
        "id": c.id,
        "client_id": c.client_id,
        "company_text": c.company_text,
        "source": c.source,
        "name": c.name,
        "role": c.role,
        "email": c.email,
        "phone": c.phone,
        "notes": c.notes,
        "is_primary": c.is_primary,
        "ai_extracted": c.ai_extracted,
    }


def _bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes", "si", "sì")


def _sync_primary(db: Session, contact: Contact) -> None:
    """Sincronizza Client.contact_* con i dati del contatto primario
    e demote tutti gli altri contatti primari dello stesso cliente."""
    cl = db.query(Client).filter(
        Client.id == contact.client_id,
        Client.tenant_id == current_tenant_id(),
    ).first()
    if cl:
        cl.contact_name = contact.name
        cl.contact_email = contact.email
        cl.contact_phone = contact.phone
        cl.contact_role = contact.role
    # un solo primario per cliente (con tenant guard)
    others = db.query(Contact).filter(
        Contact.tenant_id == current_tenant_id(),
        Contact.client_id == contact.client_id,
        Contact.id != contact.id,
        Contact.is_primary == True,  # noqa: E712
    )
    for o in others:
        o.is_primary = False


@router.get("/clients/api/{cid}/contacts", dependencies=[RequireView])
async def list_contacts(cid: int, db: Session = Depends(get_db)):
    cl = db.query(Client).filter(
        Client.id == cid,
        Client.tenant_id == current_tenant_id(),
    ).first()
    if not cl:
        raise HTTPException(404, "Cliente non trovato")
    rows = (
        db.query(Contact)
        .filter(
            Contact.tenant_id == current_tenant_id(),
            Contact.client_id == cid,
            Contact.is_active == True,  # noqa: E712
        )
        .order_by(Contact.is_primary.desc(), Contact.name)
        .all()
    )
    return {"items": [_contact_dict(c) for c in rows]}


@router.post("/clients/api/{cid}/contacts", dependencies=[RequireEdit])
async def create_contact(
    cid: int,
    name: str = Form(...),
    role: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    is_primary: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    cl = db.query(Client).filter(
        Client.id == cid,
        Client.tenant_id == current_tenant_id(),
    ).first()
    if not cl:
        raise HTTPException(404, "Cliente non trovato")
    c = Contact(
        tenant_id=current_tenant_id(),
        client_id=cid,
        name=name.strip(),
        role=role,
        email=email,
        phone=phone,
        notes=notes,
        is_primary=_bool(is_primary),
    )
    db.add(c)
    db.flush()
    if c.is_primary:
        _sync_primary(db, c)
    db.commit()
    db.refresh(c)
    return _contact_dict(c)


@router.put("/contacts/api/{cid}", dependencies=[RequireEdit])
async def update_contact(
    cid: int,
    name: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    is_primary: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    c = db.query(Contact).filter(
        Contact.id == cid,
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
    ).first()
    if not c:
        raise HTTPException(404, "Contatto non trovato")
    if name is not None:
        c.name = name.strip()
    if role is not None:
        c.role = role
    if email is not None:
        c.email = email
    if phone is not None:
        c.phone = phone
    if notes is not None:
        c.notes = notes
    if is_primary is not None:
        c.is_primary = _bool(is_primary)
    if c.is_primary:
        _sync_primary(db, c)
    db.commit()
    db.refresh(c)
    return _contact_dict(c)


@router.delete("/contacts/api/{cid}", dependencies=[RequireEdit])
async def delete_contact(cid: int, db: Session = Depends(get_db)):
    c = db.query(Contact).filter(
        Contact.id == cid,
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
    ).first()
    if not c:
        raise HTTPException(404, "Contatto non trovato")
    c.is_active = False
    db.commit()
    return {"ok": True, "id": cid}


# ── F3 Rubrica Contatti ────────────────────────────────────────────
# NB ordine rotte: le GET a path letterale (list/match) DEVONO precedere
# GET /contacts/api/{cid} (detail) — Starlette scansiona in ordine e altrimenti
# proverebbe a fare int("list")/int("match") → 422.

def _link_counts(db: Session, contact_id: int) -> dict:
    n_acq = db.query(ContactAcquisition).filter(
        ContactAcquisition.tenant_id == current_tenant_id(),
        ContactAcquisition.contact_id == contact_id).count()
    n_proj = db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == contact_id).count()
    return {"acquisitions": n_acq, "projects": n_proj}


@router.get("/contacts/api/list", dependencies=[RequireView])
async def list_contacts_rubrica(
    search: str = None, client_id: int = None, triage: str = None,
    source: str = None, db: Session = Depends(get_db),
):
    q = db.query(Contact).filter(
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
    )
    if client_id:
        q = q.filter(Contact.client_id == client_id)
    if source:
        q = q.filter(Contact.source == source)
    if search:
        like = f"%{search.strip().lower()}%"
        q = q.filter(or_(
            func.lower(Contact.name).like(like),
            func.lower(Contact.email).like(like),
            func.lower(Contact.company_text).like(like),
        ))
    rows = q.order_by(func.lower(Contact.name)).all()
    if _bool(triage):
        acq_ids = {r[0] for r in db.query(ContactAcquisition.contact_id).filter(
            ContactAcquisition.tenant_id == current_tenant_id()).all()}
        proj_ids = {r[0] for r in db.query(ContactProject.contact_id).filter(
            ContactProject.tenant_id == current_tenant_id()).all()}
        rows = [r for r in rows if r.client_id is None
                and r.id not in acq_ids and r.id not in proj_ids]
    out = []
    for r in rows:
        d = _contact_dict(r)
        d["links"] = _link_counts(db, r.id)
        out.append(d)
    return {"items": out}


@router.get("/contacts/api/match", dependencies=[RequireView])
async def match_contact(email: str, db: Session = Depends(get_db)):
    email = (email or "").strip().lower()
    if not email:
        return {"id": None}
    match = db.query(Contact).filter(
        Contact.tenant_id == current_tenant_id(),
        Contact.is_active == True,  # noqa: E712
        func.lower(Contact.email) == email,
    ).first()
    return {"id": match.id, "name": match.name} if match else {"id": None}
