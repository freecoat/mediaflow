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
from app.services import gmail
from app.services import contact_extract
from app.services.ai_provider import get_provider_for_user

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
    client_id: Optional[str] = Form(None),
    company_text: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
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
    if client_id is not None:
        # sentinel: "" o "0" -> pulisce (memoria feedback_empty_multipart_is_none)
        if client_id.strip() in ("", "0"):
            c.client_id = None
        else:
            cid_int = int(client_id)
            cl = db.query(Client).filter(
                Client.id == cid_int, Client.tenant_id == current_tenant_id()).first()
            if not cl:
                raise HTTPException(404, "Cliente non trovato")
            c.client_id = cid_int
    if company_text is not None:
        c.company_text = company_text
    if source is not None:
        c.source = source
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


def _activity_dict_local(a: Activity) -> dict:
    return {
        "id": a.id,
        "type": a.type.value,
        "direction": a.direction.value if a.direction else None,
        "occurred_at": a.occurred_at.isoformat() if a.occurred_at else None,
        "subject": a.subject,
        "body": a.body,
    }


@router.get("/contacts/api/{cid}", dependencies=[RequireView])
async def get_contact_detail(cid: int, db: Session = Depends(get_db)):
    c = fetch_or_404(db, Contact, cid, error="Contatto non trovato")
    client = None
    if c.client_id:
        cl = db.query(Client).filter(
            Client.id == c.client_id, Client.tenant_id == current_tenant_id()).first()
        if cl:
            client = {"id": cl.id, "name": cl.name}

    acq_rows = (
        db.query(ContactAcquisition, Acquisition)
        .join(Acquisition, Acquisition.id == ContactAcquisition.acquisition_id)
        .filter(ContactAcquisition.tenant_id == current_tenant_id(),
                ContactAcquisition.contact_id == cid)
        .all()
    )
    acquisitions = [{"id": a.id, "title": a.title, "role": link.role} for link, a in acq_rows]

    proj_rows = (
        db.query(ContactProject, Project)
        .join(Project, Project.id == ContactProject.project_id)
        .filter(ContactProject.tenant_id == current_tenant_id(),
                ContactProject.contact_id == cid)
        .all()
    )
    projects = [{"id": p.id, "code": p.code, "title": p.title, "role": link.role}
                for link, p in proj_rows]

    activities = (
        db.query(Activity)
        .filter(Activity.tenant_id == current_tenant_id(), Activity.contact_id == cid,
                Activity.is_active == True)  # noqa: E712
        .order_by(Activity.occurred_at.desc())
        .limit(20)
        .all()
    )

    aq_ids = [a["id"] for a in acquisitions]
    email_links = []
    if aq_ids:
        email_links = [
            {"id": e.id, "thread_id": e.thread_id, "subject": e.subject,
             "acquisition_id": e.acquisition_id}
            for e in db.query(EmailLink).filter(
                EmailLink.tenant_id == current_tenant_id(),
                EmailLink.acquisition_id.in_(aq_ids),
                EmailLink.is_active == True,  # noqa: E712
            ).order_by(EmailLink.created_at.desc()).all()
        ]

    out = _contact_dict(c)
    out.update({
        "client": client,
        "acquisitions": acquisitions,
        "projects": projects,
        "activities": [_activity_dict_local(a) for a in activities],
        "email_links": email_links,
    })
    return out


@router.post("/contacts/api/create", dependencies=[RequireEdit])
async def create_contact_standalone(
    name: str = Form(...),
    client_id: Optional[int] = Form(None),
    company_text: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Nome richiesto")
    if client_id:
        cl = db.query(Client).filter(
            Client.id == client_id, Client.tenant_id == current_tenant_id()).first()
        if not cl:
            raise HTTPException(404, "Cliente non trovato")
    if email:
        existing = db.query(Contact).filter(
            Contact.tenant_id == current_tenant_id(),
            Contact.is_active == True,  # noqa: E712
            func.lower(Contact.email) == email.strip().lower(),
        ).first()
        if existing:
            return {"existing_id": existing.id, "contact": _contact_dict(existing)}
    c = Contact(
        tenant_id=current_tenant_id(), client_id=client_id, name=name,
        company_text=company_text if not client_id else None,
        role=role, email=email, phone=phone, notes=notes, source="manual",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _contact_dict(c)


_LINK_TYPES = ("client", "acquisition", "project")


def _check_link_permission(user, target_type: str) -> None:
    if not has_permission(user, "edit_clients"):
        raise HTTPException(403, "Permesso negato")
    if target_type == "acquisition" and not has_permission(user, "manage_acquisitions"):
        raise HTTPException(403, "Permesso negato (manage_acquisitions)")
    if target_type == "project" and not has_permission(user, "edit_projects"):
        raise HTTPException(403, "Permesso negato (edit_projects)")


@router.post("/contacts/api/{cid}/link")
async def link_contact(
    cid: int,
    request: Request,
    target_type: str = Form(...),
    target_id: int = Form(...),
    role: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    if target_type not in _LINK_TYPES:
        raise HTTPException(400, "target_type deve essere client|acquisition|project")
    user = current_user(request)
    _check_link_permission(user, target_type)
    c = fetch_or_404(db, Contact, cid, error="Contatto non trovato")

    if target_type == "client":
        cl = db.query(Client).filter(
            Client.id == target_id, Client.tenant_id == current_tenant_id()).first()
        if not cl:
            raise HTTPException(404, "Cliente non trovato")
        already = c.client_id == target_id
        c.client_id = target_id
        db.commit()
        return {"ok": True, "already_linked": already}

    if target_type == "acquisition":
        fetch_or_404(db, Acquisition, target_id, error="Trattativa non trovata")
        existing = db.query(ContactAcquisition).filter(
            ContactAcquisition.tenant_id == current_tenant_id(),
            ContactAcquisition.contact_id == cid,
            ContactAcquisition.acquisition_id == target_id,
        ).first()
        if existing:
            return {"ok": True, "already_linked": True}
        db.add(ContactAcquisition(tenant_id=current_tenant_id(), contact_id=cid,
                                   acquisition_id=target_id, role=role))
        db.commit()
        return {"ok": True, "already_linked": False}

    # project
    fetch_or_404(db, Project, target_id, error="Progetto non trovato")
    existing = db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == cid,
        ContactProject.project_id == target_id,
    ).first()
    if existing:
        return {"ok": True, "already_linked": True}
    db.add(ContactProject(tenant_id=current_tenant_id(), contact_id=cid,
                          project_id=target_id, role=role))
    db.commit()
    return {"ok": True, "already_linked": False}


@router.delete("/contacts/api/{cid}/link")
async def unlink_contact(
    cid: int,
    request: Request,
    target_type: str = Form(...),
    target_id: int = Form(...),
    db: Session = Depends(get_db),
):
    if target_type not in _LINK_TYPES:
        raise HTTPException(400, "target_type deve essere client|acquisition|project")
    user = current_user(request)
    _check_link_permission(user, target_type)
    c = fetch_or_404(db, Contact, cid, error="Contatto non trovato")

    if target_type == "client":
        if c.client_id == target_id:
            c.client_id = None
            db.commit()
        return {"ok": True}
    if target_type == "acquisition":
        db.query(ContactAcquisition).filter(
            ContactAcquisition.tenant_id == current_tenant_id(),
            ContactAcquisition.contact_id == cid,
            ContactAcquisition.acquisition_id == target_id,
        ).delete()
        db.commit()
        return {"ok": True}
    db.query(ContactProject).filter(
        ContactProject.tenant_id == current_tenant_id(),
        ContactProject.contact_id == cid,
        ContactProject.project_id == target_id,
    ).delete()
    db.commit()
    return {"ok": True}


@router.post("/contacts/api/extract", dependencies=[RequireEdit])
async def extract_contacts(
    request: Request, thread_id: str = Form(...), db: Session = Depends(get_db),
):
    user = current_user(request)
    thread = gmail.get_thread(db, user.id, thread_id)
    if not thread:
        return {"candidates": []}
    return {"candidates": contact_extract.extract_from_thread(thread)}


@router.post("/contacts/api/extract/enrich", dependencies=[RequireEdit])
async def extract_contacts_enrich(
    request: Request,
    signature: str = Form(...),
    name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    role: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    company_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    user = current_user(request)
    candidate = {"name": name, "email": email, "role": role, "phone": phone,
                 "company_text": company_text}
    provider = get_provider_for_user(user.id, db)
    return contact_extract.enrich_with_ai(candidate, signature, provider)
