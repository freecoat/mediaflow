"""
Router clienti — CRUD + arricchimento AI via ricerca web.
"""
from difflib import SequenceMatcher
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Client, Project, User
from app.services.client_enrichment import enrich_client
from app.services.ai_provider import get_provider_for_user
from app.services.auth import get_current_user_from_token
from datetime import datetime
import json
import re

router = APIRouter(prefix="/clients", tags=["clients"])

CURRENT_TENANT = 1  # Fase 1-bis: tenant fisso, multi-tenant hard rinviato a Fase 7


def _resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    """Cookie JWT → user; fallback al primo utente attivo (stessa logica di ai.py/settings.py)."""
    if token:
        u = get_current_user_from_token(db, token)
        if u:
            return u
    return db.query(User).filter(User.is_active == True).order_by(User.id).first()


# ── Duplicate detection ──────────────────────────────────────

# Suffissi legali da ignorare nel matching (es. "Cattleya srl" ≈ "Cattleya")
_LEGAL_SUFFIX = re.compile(
    r"\b(srl|s\.r\.l\.|spa|s\.p\.a\.|sas|s\.a\.s\.|snc|s\.n\.c\.|"
    r"gmbh|ag|ltd|llc|inc|corp|company|co|bv|sa|nv|kg|"
    r"productions?|films?|pictures|studios?|studio|distribution)\b\.?",
    flags=re.IGNORECASE,
)

def _normalize_name(name: str) -> str:
    """Normalizza per il matching: lowercase, no suffissi legali, no doppi spazi."""
    s = (name or "").lower().strip()
    s = _LEGAL_SUFFIX.sub("", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)  # rimuove punteggiatura
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    """0.0–1.0 score basato su normalizzazione + ratio sequence matcher."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.92
    return SequenceMatcher(None, na, nb).ratio()


def find_duplicate_candidates(db: Session, name: str,
                              exclude_id: Optional[int] = None,
                              min_score: float = 0.65) -> List[dict]:
    """
    Trova clienti il cui nome è simile a `name`. Ritorna lista ordinata per score
    decrescente con: id, name, score, severity ('high'|'medium').

    severity 'high'  → score >= 0.85 (match quasi-certo, blocca creazione default)
    severity 'medium'→ 0.65 <= score < 0.85 (warning UI, non blocca)
    """
    if not name or not name.strip():
        return []
    rows = db.query(Client).filter(Client.tenant_id == CURRENT_TENANT).all()
    out = []
    for c in rows:
        if exclude_id and c.id == exclude_id:
            continue
        score = _similarity(name, c.name)
        if score >= min_score:
            out.append({
                "id": c.id,
                "name": c.name,
                "city": c.city,
                "vat_number": c.vat_number,
                "score": round(score, 3),
                "severity": "high" if score >= 0.85 else "medium",
            })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def _tpl():
    from app.main import templates
    return templates


# ── Pagine HTML ──────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def clients_page(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    clients = db.query(Client).filter(Client.tenant_id == CURRENT_TENANT).order_by(Client.name).all()
    u = _resolve_current_user(db, access_token)
    ai_enabled = get_provider_for_user(u.id if u else None, db) is not None
    return _tpl().TemplateResponse(
        "pages/clients.html",
        {"request": request, "clients": clients, "ai_enabled": ai_enabled}
    )


# ── API JSON ─────────────────────────────────────────────────

@router.get("/api")
async def list_clients(db: Session = Depends(get_db)):
    clients = db.query(Client).filter(Client.tenant_id == CURRENT_TENANT)\
        .options(joinedload(Client.projects)).order_by(Client.name).all()
    return [
        {
            "id": c.id, "name": c.name, "legal_form": c.legal_form,
            "city": c.city, "country": c.country,
            "website": c.website, "industry": c.industry,
            "contact_email": c.contact_email, "contact_phone": c.contact_phone,
            "vat_number": c.vat_number,
            "ai_enriched": c.ai_enriched,
            "projects_count": len(c.projects),
        }
        for c in clients
    ]


@router.get("/api/{client_id}")
async def get_client(client_id: int, db: Session = Depends(get_db)):
    c = db.query(Client).options(joinedload(Client.projects)).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")
    
    productions = []
    if c.recent_productions:
        try:
            productions = json.loads(c.recent_productions)
        except (json.JSONDecodeError, TypeError):
            productions = []
    
    sources = []
    if c.ai_sources:
        try:
            sources = json.loads(c.ai_sources)
        except (json.JSONDecodeError, TypeError):
            sources = []
    
    return {
        "id": c.id, "name": c.name, "legal_form": c.legal_form,
        "contact_name": c.contact_name, "contact_role": c.contact_role,
        "contact_email": c.contact_email, "contact_phone": c.contact_phone,
        "vat_number": c.vat_number, "tax_code": c.tax_code,
        "sdi_code": c.sdi_code, "pec": c.pec,
        "address": c.address, "city": c.city, "country": c.country,
        "website": c.website, "industry": c.industry,
        "company_size": c.company_size, "founded_year": c.founded_year,
        "recent_productions": productions, "notes": c.notes,
        "ai_enriched": c.ai_enriched,
        "ai_enriched_at": c.ai_enriched_at.isoformat() if c.ai_enriched_at else None,
        "ai_sources": sources,
        "projects": [
            {"id": p.id, "code": p.code, "title": p.title, "status": p.status}
            for p in c.projects
        ],
    }


@router.get("/api/check-duplicate")
async def check_duplicate(
    name: str,
    exclude_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """Ritorna candidati duplicati per il nome dato (lista ordinata per score)."""
    return find_duplicate_candidates(db, name, exclude_id=exclude_id)


@router.post("/api")
async def create_client(
    name: str = Form(...),
    legal_form: Optional[str] = Form(None),
    contact_name: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    force: bool = Form(False),  # se True, salta il check duplicati
    db: Session = Depends(get_db),
):
    # Anti-duplicato: blocca se c'è almeno un match HIGH e force=False
    if not force:
        candidates = find_duplicate_candidates(db, name)
        high = [c for c in candidates if c["severity"] == "high"]
        if high:
            raise HTTPException(409, detail={
                "message": f"Esiste già un cliente con nome simile: {high[0]['name']}",
                "duplicates": candidates,
                "hint": "Riusa il cliente esistente, oppure invia force=true per creare comunque.",
            })
    c = Client(
        tenant_id=CURRENT_TENANT,
        name=name, legal_form=legal_form, contact_name=contact_name,
        contact_email=contact_email, contact_phone=contact_phone,
        vat_number=vat_number, address=address, city=city, country=country,
        website=website, notes=notes,
    )
    db.add(c); db.commit(); db.refresh(c)
    return {"id": c.id, "name": c.name}


@router.put("/api/{client_id}")
async def update_client(
    client_id: int,
    name: Optional[str] = Form(None),
    legal_form: Optional[str] = Form(None),
    contact_name: Optional[str] = Form(None),
    contact_role: Optional[str] = Form(None),
    contact_email: Optional[str] = Form(None),
    contact_phone: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    sdi_code: Optional[str] = Form(None),
    pec: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    industry: Optional[str] = Form(None),
    company_size: Optional[str] = Form(None),
    founded_year: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")

    for field in ("name", "legal_form", "contact_name", "contact_role",
                  "contact_email", "contact_phone", "vat_number", "tax_code",
                  "sdi_code", "pec", "address", "city", "country",
                  "website", "industry", "company_size", "founded_year", "notes"):
        val = locals()[field]
        if val is not None and val != "":
            setattr(c, field, val)
    db.commit()
    return {"id": c.id, "name": c.name}


@router.delete("/api/{client_id}")
async def delete_client(client_id: int, db: Session = Depends(get_db)):
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT
    ).first()
    if not c:
        raise HTTPException(404)
    if c.projects:
        raise HTTPException(400, f"Cliente ha {len(c.projects)} progetti associati: non eliminabile")
    db.delete(c); db.commit()
    return {"ok": True}


# ── AI Enrichment ────────────────────────────────────────────

@router.post("/api/{client_id}/enrich")
async def enrich_client_api(
    client_id: int,
    use_name_only: bool = Form(True),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """
    Arricchisce il cliente con dati dal web via AI.
    Se use_name_only=False, usa anche città/paese già noti per query più mirate.
    """
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")

    u = _resolve_current_user(db, access_token)
    provider = get_provider_for_user(u.id if u else None, db)
    if not provider:
        raise HTTPException(503, "AI provider non configurato. Vai in Impostazioni → AI.")

    known_info = None
    if not use_name_only:
        known_info = {"city": c.city, "country": c.country}

    enriched = enrich_client(c.name, known_info=known_info, provider=provider)
    if not enriched:
        raise HTTPException(500, "Arricchimento fallito. Controlla i log.")
    
    # Applica i campi solo se attualmente vuoti (non sovrascrivere dati inseriti manualmente)
    # oppure se c è già stato AI-enriched (rigenerazione)
    overwrite = c.ai_enriched
    
    for field in ("legal_form", "vat_number", "tax_code", "address", "city",
                  "country", "website", "contact_email", "contact_phone",
                  "industry", "company_size", "founded_year", "notes",
                  "recent_productions", "ai_sources"):
        new_val = enriched.get(field)
        if new_val is None or new_val == "":
            continue
        current = getattr(c, field, None)
        if overwrite or not current:
            setattr(c, field, new_val)
    
    c.ai_enriched = True
    c.ai_enriched_at = datetime.utcnow()
    db.commit()
    db.refresh(c)
    
    return {
        "ok": True,
        "client_id": c.id,
        "fields_updated": [k for k in enriched.keys()
                           if k not in ("ai_enriched", "ai_enriched_at", "web_search_used")],
        "web_search_used": enriched.get("web_search_used", False),
    }


@router.post("/api/search-enrich")
async def search_and_create(
    name: str = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """
    Crea un nuovo cliente cercando direttamente sul web.
    Utile per onboarding: "Cattleya srl" → crea + arricchisce in un colpo solo.
    """
    u = _resolve_current_user(db, access_token)
    provider = get_provider_for_user(u.id if u else None, db)
    if not provider:
        raise HTTPException(503, "AI provider non configurato")

    existing = db.query(Client).filter(
        Client.tenant_id == CURRENT_TENANT,
        Client.name.ilike(f"%{name}%"),
    ).first()
    if existing:
        raise HTTPException(400, f"Cliente '{existing.name}' già esistente (ID {existing.id})")

    enriched = enrich_client(name, provider=provider)
    if not enriched:
        raise HTTPException(500, "Arricchimento fallito")

    client = Client(
        tenant_id=CURRENT_TENANT,
        name=name, ai_enriched=True, ai_enriched_at=datetime.utcnow(),
    )
    for field in ("legal_form", "vat_number", "tax_code", "address", "city",
                  "country", "website", "contact_email", "contact_phone",
                  "industry", "company_size", "founded_year", "notes",
                  "recent_productions", "ai_sources"):
        val = enriched.get(field)
        if val:
            setattr(client, field, val)
    db.add(client); db.commit(); db.refresh(client)
    return {"ok": True, "client_id": client.id, "name": client.name}
