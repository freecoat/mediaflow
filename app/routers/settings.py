"""
Router impostazioni — pagina /settings con tema, ordinamento sidebar, account utente,
e configurazione AI per-utente (provider, api_key cifrata, modello).
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, Form, Cookie
from fastapi.responses import HTMLResponse
from typing import Optional
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, WorkingHoursPolicy
from app.models.models import UserAISettings
from datetime import time
from app.services.auth import get_current_user_from_token, hash_password, verify_password
from app.services.ai_provider import (
    PROVIDER_LABELS, PROVIDER_MODELS, ProviderConfig, build_provider,
)
from app.services.crypto import encrypt_secret, decrypt_secret

router = APIRouter(prefix="/settings", tags=["settings"])


def _tpl():
    from app.main import templates
    return templates


def _resolve_current_user(db: Session, token: Optional[str]) -> Optional[User]:
    """Risolve l'utente corrente dal cookie. Se non loggato, ritorna il primo admin
    attivo come fallback (utile in modalità demo / single-tenant interno)."""
    if token:
        u = get_current_user_from_token(db, token)
        if u:
            return u
    return db.query(User).filter(User.is_active == True).order_by(User.id).first()


@router.get("/", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    user = _resolve_current_user(db, access_token)
    return _tpl().TemplateResponse(
        "pages/settings.html",
        {"request": request, "user": user},
    )


@router.get("/api/me")
async def get_me(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role, "is_active": u.is_active,
    }


@router.put("/api/me")
async def update_me(
    full_name: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    if full_name is not None and full_name.strip():
        u.full_name = full_name.strip()
    if email is not None and email.strip() and email != u.email:
        existing = db.query(User).filter(User.email == email, User.id != u.id).first()
        if existing:
            raise HTTPException(400, "Email già in uso da un altro utente")
        u.email = email.strip()
    db.commit()
    return {"ok": True, "id": u.id, "full_name": u.full_name, "email": u.email}


@router.put("/api/me/password")
async def change_password(
    old_password: str = Form(...),
    new_password: str = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    if not verify_password(old_password, u.hashed_password):
        raise HTTPException(400, "Password attuale non corretta")
    if len(new_password) < 6:
        raise HTTPException(400, "La nuova password deve avere almeno 6 caratteri")
    u.hashed_password = hash_password(new_password)
    db.commit()
    return {"ok": True}


# ── AI SETTINGS PER-UTENTE ────────────────────────────────────

def _ai_row_dict(row: Optional[UserAISettings]) -> dict:
    """Serializza una riga UserAISettings senza esporre la chiave in chiaro."""
    if not row:
        return {}
    return {
        "provider": row.provider,
        "model": row.model,
        "base_url": row.base_url,
        "has_key": bool(row.api_key_encrypted),
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "last_error": row.last_error,
    }


@router.get("/api/ai")
async def ai_settings_get(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """
    Stato AI per l'utente corrente:
    - lista provider supportati con relativi modelli disponibili
    - config salvata per ciascun provider (senza api_key in chiaro)
    - provider attualmente attivo
    """
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    rows = {r.provider: r for r in
            db.query(UserAISettings).filter(UserAISettings.user_id == u.id).all()}
    providers = []
    for pid, label in PROVIDER_LABELS.items():
        providers.append({
            "id": pid,
            "label": label,
            "models": PROVIDER_MODELS.get(pid, []),
            "config": _ai_row_dict(rows.get(pid)),
            "needs_api_key": pid != "ollama",
        })
    return {
        "active_provider": u.active_ai_provider,
        "providers": providers,
    }


@router.post("/api/ai/save")
async def ai_settings_save(
    provider: str = Form(...),
    api_key: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    base_url: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Salva la configurazione di un singolo provider per l'utente corrente.
    Se `api_key` è vuoto, mantiene quello esistente (non lo sovrascrive)."""
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    if provider not in PROVIDER_LABELS:
        raise HTTPException(400, f"Provider non supportato: {provider}")

    row = db.query(UserAISettings).filter(
        UserAISettings.user_id == u.id, UserAISettings.provider == provider).first()
    if not row:
        row = UserAISettings(user_id=u.id, provider=provider)
        db.add(row)

    if api_key:
        row.api_key_encrypted = encrypt_secret(api_key.strip())
        row.verified_at = None
        row.last_error = None
    if model is not None:
        row.model = model.strip() or None
    if base_url is not None:
        row.base_url = base_url.strip() or None

    db.commit()
    db.refresh(row)
    return {"ok": True, "config": _ai_row_dict(row)}


@router.post("/api/ai/test")
async def ai_settings_test(
    provider: str = Form(...),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Testa la connessione al provider con la config salvata.
    Ollama: chiama /api/tags. Altri: una `complete()` minima."""
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    row = db.query(UserAISettings).filter(
        UserAISettings.user_id == u.id, UserAISettings.provider == provider).first()
    if not row:
        raise HTTPException(404, "Configurazione non salvata")

    api_key = decrypt_secret(row.api_key_encrypted) if row.api_key_encrypted else None
    if provider != "ollama" and not api_key:
        raise HTTPException(400, "API key mancante o non leggibile")

    cfg = ProviderConfig(provider=provider, api_key=api_key,
                         model=row.model, base_url=row.base_url)
    try:
        prov = build_provider(cfg)
        # Ping minimale: 1 token max basta per validare auth
        out = prov.complete(
            system="Rispondi solo OK.",
            user="ping",
            max_tokens=10,
            temperature=0.0,
        )
        row.verified_at = datetime.utcnow()
        row.last_error = None
        db.commit()
        return {"ok": True, "provider_name": prov.name, "sample": (out or "").strip()[:80]}
    except Exception as e:
        row.last_error = str(e)[:500]
        db.commit()
        raise HTTPException(400, f"Test fallito: {e}")


@router.post("/api/ai/activate")
async def ai_settings_activate(
    provider: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Imposta il provider attivo per l'utente. provider=None disabilita l'AI."""
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    if provider in (None, "", "disabled"):
        u.active_ai_provider = None
        db.commit()
        return {"ok": True, "active_provider": None}
    if provider not in PROVIDER_LABELS:
        raise HTTPException(400, f"Provider non supportato: {provider}")
    row = db.query(UserAISettings).filter(
        UserAISettings.user_id == u.id, UserAISettings.provider == provider).first()
    if not row:
        raise HTTPException(400, "Configura il provider prima di attivarlo")
    if provider != "ollama" and not row.api_key_encrypted:
        raise HTTPException(400, "Salva una API key prima di attivare il provider")
    u.active_ai_provider = provider
    db.commit()
    return {"ok": True, "active_provider": provider}


@router.delete("/api/ai/{provider}")
async def ai_settings_delete(
    provider: str,
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Rimuove la configurazione di un provider per l'utente corrente."""
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(404, "Utente non trovato")
    row = db.query(UserAISettings).filter(
        UserAISettings.user_id == u.id, UserAISettings.provider == provider).first()
    if row:
        db.delete(row)
        if u.active_ai_provider == provider:
            u.active_ai_provider = None
        db.commit()
    return {"ok": True}


# ── Working hours policy (E3 v3.4.17) ──────────────────────────────

CURRENT_TENANT_FALLBACK = 1


def _serialize_policy(p: WorkingHoursPolicy) -> dict:
    return {
        "id": p.id, "name": p.name, "is_default": p.is_default,
        "morning_start": p.morning_start.strftime("%H:%M") if p.morning_start else None,
        "morning_end": p.morning_end.strftime("%H:%M") if p.morning_end else None,
        "afternoon_start": p.afternoon_start.strftime("%H:%M") if p.afternoon_start else None,
        "afternoon_end": p.afternoon_end.strftime("%H:%M") if p.afternoon_end else None,
        "working_days": p.working_days,
        "holidays_country": p.holidays_country,
        "daily_hours_threshold": p.daily_hours_threshold,
        "weekly_hours_threshold": p.weekly_hours_threshold,
        "overtime_multiplier": p.overtime_multiplier,
        "night_multiplier": p.night_multiplier,
        "sunday_multiplier": p.sunday_multiplier,
        "holiday_multiplier": p.holiday_multiplier,
        "night_start": p.night_start.strftime("%H:%M") if p.night_start else None,
        "night_end": p.night_end.strftime("%H:%M") if p.night_end else None,
        "overtime_brackets": p.overtime_brackets or [],
        "ccnl_label": p.ccnl_label,
    }


def _parse_time(s: Optional[str]) -> Optional[time]:
    if not s:
        return None
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except Exception:
        raise HTTPException(400, f"Orario non valido: {s}")


def _ensure_default_policy(db: Session) -> WorkingHoursPolicy:
    """v3.5.0-alpha.21: auto-crea una policy default minima al primo accesso.

    Pre-alpha.21: se nessuna WorkingHoursPolicy esisteva nel tenant, la pagina
    /settings#hours mostrava form vuoto e il save falliva (PUT richiede id).
    Ora se non esiste viene creata con valori sensati italiani (8h/40h CCNL
    base, 1.30/1.25/1.50/2.00 multipliers, fascia notturna 22-06, festività IT).
    """
    p = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
        WorkingHoursPolicy.is_default == True,  # noqa: E712
    ).first()
    if p:
        return p
    p = WorkingHoursPolicy(
        tenant_id=CURRENT_TENANT_FALLBACK,
        name="Italia standard",
        is_default=True,
        morning_start=time(9, 0), morning_end=time(13, 0),
        afternoon_start=time(14, 0), afternoon_end=time(18, 0),
        working_days=31,  # lun-ven
        holidays_country="IT",
        daily_hours_threshold=8.0, weekly_hours_threshold=40.0,
        overtime_multiplier=1.30, night_multiplier=1.25,
        sunday_multiplier=1.50, holiday_multiplier=2.00,
        night_start=time(22, 0), night_end=time(6, 0),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/api/working-hours")
async def get_working_hours(db: Session = Depends(get_db)):
    """Ritorna tutte le policy del tenant (di default 1: la 'Italia standard')."""
    # v3.5.0-alpha.21: garantisce esistenza policy default (auto-crea se assente)
    _ensure_default_policy(db)
    pols = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
    ).order_by(WorkingHoursPolicy.is_default.desc(), WorkingHoursPolicy.id).all()
    return [_serialize_policy(p) for p in pols]


@router.put("/api/working-hours/{policy_id}")
async def update_working_hours(
    policy_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    morning_start: Optional[str] = Form(None),
    morning_end: Optional[str] = Form(None),
    afternoon_start: Optional[str] = Form(None),
    afternoon_end: Optional[str] = Form(None),
    working_days: Optional[int] = Form(None),
    holidays_country: Optional[str] = Form(None),
    daily_hours_threshold: Optional[float] = Form(None),
    weekly_hours_threshold: Optional[float] = Form(None),
    overtime_multiplier: Optional[float] = Form(None),
    night_multiplier: Optional[float] = Form(None),
    sunday_multiplier: Optional[float] = Form(None),
    holiday_multiplier: Optional[float] = Form(None),
    night_start: Optional[str] = Form(None),
    night_end: Optional[str] = Form(None),
    overtime_brackets: Optional[str] = Form(None),  # JSON string
    ccnl_label: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # v3.5.0-alpha.21: RBAC — solo manager+ può modificare working hours.
    from app.services.rbac import current_user_optional, can_edit_settings
    user = current_user_optional(request)
    if not can_edit_settings(user):
        raise HTTPException(
            403,
            "Non hai i permessi per modificare gli orari lavorativi. "
            "Servono permessi di manager o superiore.",
        )
    p = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.id == policy_id,
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
    ).first()
    if not p:
        raise HTTPException(404, "Policy non trovata")
    if name is not None: p.name = name
    if morning_start is not None: p.morning_start = _parse_time(morning_start)
    if morning_end is not None: p.morning_end = _parse_time(morning_end)
    if afternoon_start is not None: p.afternoon_start = _parse_time(afternoon_start) if afternoon_start else None
    if afternoon_end is not None: p.afternoon_end = _parse_time(afternoon_end) if afternoon_end else None
    if working_days is not None: p.working_days = working_days
    if holidays_country is not None: p.holidays_country = (holidays_country or None)
    if daily_hours_threshold is not None: p.daily_hours_threshold = daily_hours_threshold
    if weekly_hours_threshold is not None: p.weekly_hours_threshold = weekly_hours_threshold
    if overtime_multiplier is not None: p.overtime_multiplier = overtime_multiplier
    if night_multiplier is not None: p.night_multiplier = night_multiplier
    if sunday_multiplier is not None: p.sunday_multiplier = sunday_multiplier
    if holiday_multiplier is not None: p.holiday_multiplier = holiday_multiplier
    if night_start is not None: p.night_start = _parse_time(night_start) if night_start else None
    if night_end is not None: p.night_end = _parse_time(night_end) if night_end else None
    # v3.4.32.2 — scaglioni overtime + ccnl label
    if overtime_brackets is not None:
        if not overtime_brackets.strip() or overtime_brackets.strip() == "[]":
            p.overtime_brackets = None
        else:
            import json as _json
            try:
                parsed = _json.loads(overtime_brackets)
                if not isinstance(parsed, list):
                    raise HTTPException(400, "overtime_brackets deve essere una lista JSON")
                # Validazione minima: from_hour numerico, multiplier ≥ 1
                cleaned = []
                for b in parsed:
                    if not isinstance(b, dict): continue
                    fh = float(b.get("from_hour", 0))
                    mu = float(b.get("multiplier", 1.0))
                    if mu < 1.0:
                        raise HTTPException(400, "multiplier in overtime_brackets deve essere ≥ 1.0")
                    cleaned.append({"from_hour": fh, "multiplier": mu})
                cleaned.sort(key=lambda x: x["from_hour"])
                p.overtime_brackets = cleaned if cleaned else None
            except (ValueError, TypeError) as e:
                raise HTTPException(400, f"overtime_brackets JSON non valido: {e}")
    if ccnl_label is not None:
        p.ccnl_label = (ccnl_label.strip() or None)
    if p.morning_end <= p.morning_start:
        raise HTTPException(400, "morning_end deve essere > morning_start")
    if p.daily_hours_threshold <= 0 or p.weekly_hours_threshold <= 0:
        raise HTTPException(400, "Soglie ore devono essere > 0")
    for f in ("overtime_multiplier", "night_multiplier", "sunday_multiplier", "holiday_multiplier"):
        if getattr(p, f) < 1.0:
            raise HTTPException(400, f"{f} deve essere ≥ 1.0")
    db.commit()
    db.refresh(p)
    return _serialize_policy(p)


# ── v3.5.0-alpha.52: DATI AZIENDALI per fattura formale ───────

def _require_admin(user: Optional[User]):
    if not user or user.role != "admin":
        raise HTTPException(403, "Solo gli admin possono modificare i dati aziendali")


@router.get("/api/company")
async def company_get(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Dati aziendali del tenant corrente, usati come header fattura."""
    from app.models import Tenant
    u = _resolve_current_user(db, access_token)
    if not u:
        raise HTTPException(401, "Utente non autenticato")
    t = db.query(Tenant).filter(Tenant.id == 1).first()
    if not t:
        raise HTTPException(404, "Tenant non configurato")
    return {
        "id": t.id,
        "name": t.name,
        "legal_name": t.legal_name,
        "vat_number": t.vat_number,
        "tax_code": t.tax_code,
        "address": t.address,
        "email": t.email,
        "phone": t.phone,
        "website": t.website,
        "logo_path": t.logo_path,
        "iban": t.iban,
        "sdi_code": t.sdi_code,
        "rea_number": t.rea_number,
        "fiscal_capital": t.fiscal_capital,
        "fiscal_regime": t.fiscal_regime,
        "payment_terms_default": t.payment_terms_default,
        "payment_method_default": t.payment_method_default,
        "invoice_footer": t.invoice_footer,
        "default_currency": t.default_currency,
        "default_vat_rate": t.default_vat_rate,
        "default_language": t.default_language,
        # v3.5.0-alpha.66.13 — Branding
        "tagline": getattr(t, "tagline", None),
        "brand_color": getattr(t, "brand_color", None) or "#6272f5",
        "show_powered_by": bool(getattr(t, "show_powered_by", True)),
        "document_header": getattr(t, "document_header", None),
    }


@router.put("/api/company")
async def company_update(
    name: Optional[str] = Form(None),
    legal_name: Optional[str] = Form(None),
    vat_number: Optional[str] = Form(None),
    tax_code: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    phone: Optional[str] = Form(None),
    website: Optional[str] = Form(None),
    iban: Optional[str] = Form(None),
    sdi_code: Optional[str] = Form(None),
    rea_number: Optional[str] = Form(None),
    fiscal_capital: Optional[str] = Form(None),
    fiscal_regime: Optional[str] = Form(None),
    payment_terms_default: Optional[int] = Form(None),
    payment_method_default: Optional[str] = Form(None),
    invoice_footer: Optional[str] = Form(None),
    default_vat_rate: Optional[float] = Form(None),
    # v3.5.0-alpha.66.13 — Branding
    tagline: Optional[str] = Form(None),
    brand_color: Optional[str] = Form(None),
    document_header: Optional[str] = Form(None),
    show_powered_by: Optional[str] = Form(None),
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Admin only. Aggiorna anagrafica fiscale del tenant.

    NOTA: le fatture già emesse hanno snapshot immutabili dei dati al
    momento dell'emissione, quindi modifiche qui NON corrompono fatture
    storiche.
    """
    from app.models import Tenant
    u = _resolve_current_user(db, access_token)
    _require_admin(u)
    t = db.query(Tenant).filter(Tenant.id == 1).first()
    if not t:
        raise HTTPException(404, "Tenant non configurato")
    # Update solo i campi forniti (form parzialmente compilati)
    fields = dict(
        name=name, legal_name=legal_name, vat_number=vat_number,
        tax_code=tax_code, address=address, email=email, phone=phone,
        website=website, iban=iban, sdi_code=sdi_code, rea_number=rea_number,
        fiscal_capital=fiscal_capital, fiscal_regime=fiscal_regime,
        payment_terms_default=payment_terms_default,
        payment_method_default=payment_method_default,
        invoice_footer=invoice_footer, default_vat_rate=default_vat_rate,
        # Branding
        tagline=tagline, brand_color=brand_color,
        document_header=document_header,
    )
    for k, v in fields.items():
        if v is None:
            continue
        # stringhe vuote ammesse come "azzera campo" (Optional)
        if isinstance(v, str):
            v = v.strip() or None
        # Validazione brand_color: hex 6 caratteri
        if k == "brand_color" and v:
            import re as _re
            if not _re.match(r"^#[0-9a-fA-F]{6}$", v):
                v = None  # silenziosamente droppa hex non validi
        setattr(t, k, v)
    # Boolean separato (Form invia 'true'/'false' string)
    if show_powered_by is not None:
        t.show_powered_by = (show_powered_by.strip().lower() == "true")
    db.commit()
    db.refresh(t)
    return {"ok": True, "id": t.id}


@router.post("/api/company/logo")
async def company_logo_upload(
    request: Request,
    db: Session = Depends(get_db),
    access_token: Optional[str] = Cookie(None),
):
    """Upload logo aziendale. Salva in `uploads/tenant/logo.{ext}`."""
    from fastapi import UploadFile, File
    from pathlib import Path
    from app.models import Tenant
    u = _resolve_current_user(db, access_token)
    _require_admin(u)
    form = await request.form()
    f = form.get("file")
    if f is None or not hasattr(f, "filename"):
        raise HTTPException(400, "Nessun file fornito")
    fname = (f.filename or "").lower()
    ext = None
    for e in (".png", ".jpg", ".jpeg", ".webp"):
        if fname.endswith(e):
            ext = e
            break
    if not ext:
        raise HTTPException(400, "Estensione non ammessa (png/jpg/webp)")
    content = await f.read()
    if len(content) > 1_000_000:
        raise HTTPException(400, "Logo troppo grande (max 1MB)")
    target_dir = Path("uploads") / "tenant"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"logo{ext}"
    # Pulisci eventuali altri formati per non lasciare residui ambigui
    for e in (".png", ".jpg", ".jpeg", ".webp"):
        old = target_dir / f"logo{e}"
        if old.exists() and old != target:
            try:
                old.unlink()
            except Exception:
                pass
    target.write_bytes(content)
    t = db.query(Tenant).filter(Tenant.id == 1).first()
    t.logo_path = str(target.as_posix())
    db.commit()
    return {"ok": True, "logo_path": t.logo_path}
