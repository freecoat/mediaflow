"""
Router clienti — CRUD + arricchimento AI via ricerca web.
"""
from difflib import SequenceMatcher
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse
from typing import Optional, List
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models import Client, ClientWork, Project, User
from app.services.client_enrichment import enrich_client
from app.services.ai_provider import get_provider_for_user
from app.services.auth import get_current_user_from_token
from datetime import datetime
import json
import re

router = APIRouter(prefix="/clients", tags=["clients"])

CURRENT_TENANT = 1  # Fase 1-bis: tenant fisso, multi-tenant hard rinviato a Fase 7


# v3.5.0-alpha.66.14.2: alias verso il singleton in app.services.auth.
# La logica fail-closed (settings.auth_required=True → no fallback) vive lì.
from app.services.auth import resolve_current_user as _resolve_current_user  # noqa: E402,F401


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


@router.get("/{client_id}/works", response_class=HTMLResponse)
async def client_works_page(
    client_id: int,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """v3.5.0-alpha.28: pagina dedicata filmografia cliente.

    Sostituisce la tab "Filmografia" nella scheda cliente. Vista più ampia
    con campi estesi (sinossi, finanziamenti pubblici, cast & crew, link
    esterni, premi, data uscita).
    """
    c = (
        db.query(Client)
        .filter(Client.id == client_id, Client.tenant_id == CURRENT_TENANT)
        .first()
    )
    if not c:
        raise HTTPException(404, "Cliente non trovato")
    u = _resolve_current_user(db, access_token)
    ai_enabled = get_provider_for_user(u.id if u else None, db) is not None
    return _tpl().TemplateResponse(
        "pages/client_works.html",
        {"request": request, "client": c, "ai_enabled": ai_enabled},
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


# ── ClientWork (filmografia) — v3.5.0-alpha.25 ───────────────

def _safe_json_load(raw, default):
    if not raw:
        return default
    try:
        v = json.loads(raw)
        return v if v is not None else default
    except Exception:
        return default


def _work_dict(w: ClientWork) -> dict:
    """Serializza un ClientWork in JSON-friendly."""
    return {
        "id": w.id,
        "client_id": w.client_id,
        "title": w.title,
        "year": w.year,
        "kind": w.kind,
        "our_role": w.our_role,
        "director": w.director,
        "country": w.country,
        "sources": _safe_json_load(w.sources_json, []),  # lista di {name, url}
        "notes": w.notes,
        # v3.5.0-alpha.28 — campi estesi
        "synopsis": w.synopsis,
        "release_date": w.release_date.isoformat() if w.release_date else None,
        "funding_public": _safe_json_load(w.funding_public, None),
        "cast_crew": _safe_json_load(w.cast_crew, None),
        "external_links": _safe_json_load(w.external_links, []),
        "awards": _safe_json_load(w.awards, []),
        "ai_imported": bool(w.ai_imported),
        "created_at": w.created_at.isoformat() if w.created_at else None,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    }


@router.get("/api/{client_id}/works")
async def list_client_works(client_id: int, db: Session = Depends(get_db)):
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT,
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")
    items = (
        db.query(ClientWork)
        .filter(ClientWork.client_id == client_id, ClientWork.tenant_id == CURRENT_TENANT)
        .order_by(ClientWork.year.desc().nullslast(), ClientWork.title.asc())
        .all()
    )
    return [_work_dict(w) for w in items]


@router.post("/api/{client_id}/works")
async def create_client_work(
    client_id: int,
    title: str = Form(...),
    year: Optional[int] = Form(None),
    kind: Optional[str] = Form(None),
    our_role: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    sources: Optional[str] = Form(None),  # JSON string [{name,url}, ...]
    notes: Optional[str] = Form(None),
    ai_imported: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Crea una nuova opera nella filmografia del cliente. Idempotente su
    (title, year): se esiste già un record con stesso titolo+anno, ritorna
    quello esistente con HTTP 200 (no errore) per non rompere il flusso AI
    quando l'utente importa di nuovo opere già presenti."""
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT,
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")
    title = (title or "").strip()
    if not title:
        raise HTTPException(400, "Title è obbligatorio")
    # Idempotency check: stessa (client, title.lower, year)
    existing = (
        db.query(ClientWork)
        .filter(
            ClientWork.client_id == client_id,
            ClientWork.tenant_id == CURRENT_TENANT,
            ClientWork.title.ilike(title),
            ClientWork.year == year,
        )
        .first()
    )
    if existing:
        return {"ok": True, "duplicate": True, **_work_dict(existing)}

    sources_clean = None
    if sources:
        try:
            parsed = json.loads(sources)
            if isinstance(parsed, list):
                sources_clean = json.dumps([
                    s for s in parsed if isinstance(s, dict) and s.get("url")
                ])
        except Exception:
            sources_clean = None

    w = ClientWork(
        tenant_id=CURRENT_TENANT,
        client_id=client_id,
        title=title[:255],
        year=year,
        kind=(kind or None),
        our_role=(our_role or None),
        director=(director or None),
        country=(country or None),
        sources_json=sources_clean,
        notes=(notes or None),
        ai_imported=bool(ai_imported),
    )
    db.add(w); db.commit(); db.refresh(w)
    return {"ok": True, "duplicate": False, **_work_dict(w)}


@router.put("/api/{client_id}/works/{work_id}")
async def update_client_work(
    client_id: int,
    work_id: int,
    title: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    kind: Optional[str] = Form(None),
    our_role: Optional[str] = Form(None),
    director: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    sources: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    # v3.5.0-alpha.28 — campi estesi (tutti opzionali, JSON quando applicabile)
    synopsis: Optional[str] = Form(None),
    release_date: Optional[str] = Form(None),
    funding_public: Optional[str] = Form(None),
    cast_crew: Optional[str] = Form(None),
    external_links: Optional[str] = Form(None),
    awards: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    w = (
        db.query(ClientWork)
        .filter(
            ClientWork.id == work_id,
            ClientWork.client_id == client_id,
            ClientWork.tenant_id == CURRENT_TENANT,
        )
        .first()
    )
    if not w:
        raise HTTPException(404, "Opera non trovata")
    if title is not None and title.strip():
        w.title = title.strip()[:255]
    if year is not None:
        w.year = year if year else None
    if kind is not None:
        w.kind = (kind or None)
    if our_role is not None:
        w.our_role = (our_role or None)
    if director is not None:
        w.director = (director or None)
    if country is not None:
        w.country = (country or None)
    if notes is not None:
        w.notes = (notes or None)
    if synopsis is not None:
        w.synopsis = (synopsis or None)
    if release_date is not None:
        rd = (release_date or "").strip()
        if not rd:
            w.release_date = None
        else:
            try:
                from datetime import date as _date
                w.release_date = _date.fromisoformat(rd)
            except ValueError:
                pass  # ignora valori non validi
    # JSON fields: passa "" o "null" per cancellare, JSON valido per setting.
    for fname, fval in (
        ("funding_public", funding_public),
        ("cast_crew", cast_crew),
        ("external_links", external_links),
        ("awards", awards),
    ):
        if fval is None:
            continue
        cleaned = (fval or "").strip()
        if cleaned in ("", "null"):
            setattr(w, fname, None)
            continue
        try:
            json.loads(cleaned)  # solo per validare
            setattr(w, fname, cleaned)
        except Exception:
            pass  # ignora JSON invalidi
    if sources is not None:
        try:
            parsed = json.loads(sources)
            if isinstance(parsed, list):
                w.sources_json = json.dumps([
                    s for s in parsed if isinstance(s, dict) and s.get("url")
                ])
        except Exception:
            pass
    db.commit(); db.refresh(w)
    return _work_dict(w)


@router.delete("/api/{client_id}/works/{work_id}")
async def delete_client_work(
    client_id: int, work_id: int, db: Session = Depends(get_db),
):
    w = (
        db.query(ClientWork)
        .filter(
            ClientWork.id == work_id,
            ClientWork.client_id == client_id,
            ClientWork.tenant_id == CURRENT_TENANT,
        )
        .first()
    )
    if not w:
        raise HTTPException(404, "Opera non trovata")
    db.delete(w); db.commit()
    return {"ok": True}


@router.post("/api/{client_id}/search-filmography")
async def search_filmography_api(
    client_id: int,
    extra_hint: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Cerca via AI le opere del cliente sulle 4 fonti pubbliche
    (filmitalia.org, cinema.cultura.gov.it, IMDB, MyMovies).

    NESSUNA scrittura DB qui. Ritorna proposte. L'utente importa via
    `POST /api/{client_id}/works` per ogni opera selezionata.
    """
    c = db.query(Client).filter(
        Client.id == client_id, Client.tenant_id == CURRENT_TENANT,
    ).first()
    if not c:
        raise HTTPException(404, "Cliente non trovato")

    u = _resolve_current_user(db, access_token)
    provider = get_provider_for_user(u.id if u else None, db)
    if not provider:
        raise HTTPException(503, "AI provider non configurato. Vai in Impostazioni → AI.")

    from app.services.filmography import search_filmography
    result = search_filmography(c.name, provider=provider, extra_hint=extra_hint)
    if not result:
        raise HTTPException(500, "Ricerca filmografia fallita")

    # Marca con ID già esistenti per UI dedup-friendly
    existing = (
        db.query(ClientWork)
        .filter(ClientWork.client_id == client_id, ClientWork.tenant_id == CURRENT_TENANT)
        .all()
    )
    existing_keys = {(w.title.strip().lower(), w.year) for w in existing}
    for w in result.get("works", []):
        key = (w["title"].strip().lower(), w.get("year"))
        w["already_imported"] = key in existing_keys

    return {
        "client_id": client_id,
        "client_name": c.name,
        **result,
    }
