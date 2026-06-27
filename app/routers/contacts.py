"""
app/routers/contacts.py

Contatti multipli per cliente — sotto-risorsa di Client.
Settare is_primary=True sincronizza Client.contact_name/email/phone/role
e demote tutti gli altri primari dello stesso cliente.

feat/acquisizioni-fase1 — Task 10
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session

from app.database import get_db
from app.context import current_tenant_id
from app.models.models import Contact, Client
from app.services.rbac import requires_permission

router = APIRouter(tags=["contacts"])
RequireView = Depends(requires_permission("view_clients"))
RequireEdit = Depends(requires_permission("edit_clients"))


def _contact_dict(c: Contact) -> dict:
    return {
        "id": c.id,
        "client_id": c.client_id,
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
    # un solo primario per cliente
    others = db.query(Contact).filter(
        Contact.client_id == contact.client_id,
        Contact.id != contact.id,
        Contact.is_primary == True,  # noqa: E712
    )
    for o in others:
        o.is_primary = False


@router.get("/clients/api/{cid}/contacts", dependencies=[RequireView])
async def list_contacts(cid: int, db: Session = Depends(get_db)):
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
