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
from app.models import User, WorkingHoursPolicy, Resource, Holiday
from app.models.models import UserAISettings
from datetime import time
from app.services.auth import get_current_user_from_token, hash_password, verify_password
from app.services.ai_provider import (
    PROVIDER_LABELS, PROVIDER_MODELS, ProviderConfig, build_provider,
)
from app.services.crypto import encrypt_secret, decrypt_secret
from app.context import current_tenant_id

router = APIRouter(prefix="/settings", tags=["settings"])


def _tpl():
    from app.main import templates
    return templates


# v3.5.0-alpha.66.14.2: alias verso il singleton in app.services.auth.
# La logica fail-closed (settings.auth_required=True → no fallback) vive lì.
from app.services.auth import resolve_current_user as _resolve_current_user  # noqa: E402,F401


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
        # v3.5.0-alpha.106: error handling esplicito per encryption failure
        # (es. AI_KEY_ENCRYPTION_KEY mancante nel .env del deploy). Prima
        # ritornava 500 generico, ora 503 con messaggio chiaro.
        try:
            row.api_key_encrypted = encrypt_secret(api_key.strip())
        except RuntimeError as e:
            raise HTTPException(503, f"Cifratura API key fallita: {e}")
        except Exception as e:
            raise HTTPException(503, f"Errore cifratura: {e}")
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
        "permit_multiplier": getattr(p, "permit_multiplier", 1.0),
        "night_start": p.night_start.strftime("%H:%M") if p.night_start else None,
        "night_end": p.night_end.strftime("%H:%M") if p.night_end else None,
        "overtime_brackets": p.overtime_brackets or [],
        "ccnl_label": p.ccnl_label,
        # α.172.29 — Accrual ferie/ROL/permessi
        "annual_leave_days_default": getattr(p, "annual_leave_days_default", 26.0),
        "monthly_rol_hours_accrual": getattr(p, "monthly_rol_hours_accrual", 8.0),
        "monthly_permit_hours_accrual": getattr(p, "monthly_permit_hours_accrual", 8.0),
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
    permit_multiplier: Optional[float] = Form(None),
    night_start: Optional[str] = Form(None),
    night_end: Optional[str] = Form(None),
    overtime_brackets: Optional[str] = Form(None),  # JSON string
    ccnl_label: Optional[str] = Form(None),
    annual_leave_days_default: Optional[float] = Form(None),
    monthly_rol_hours_accrual: Optional[float] = Form(None),
    monthly_permit_hours_accrual: Optional[float] = Form(None),
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
    if permit_multiplier is not None: p.permit_multiplier = permit_multiplier
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
    if annual_leave_days_default is not None:
        if annual_leave_days_default < 0 or annual_leave_days_default > 365:
            raise HTTPException(400, "annual_leave_days_default fuori range [0..365]")
        p.annual_leave_days_default = annual_leave_days_default
    if monthly_rol_hours_accrual is not None:
        if monthly_rol_hours_accrual < 0 or monthly_rol_hours_accrual > 200:
            raise HTTPException(400, "monthly_rol_hours_accrual fuori range [0..200]")
        p.monthly_rol_hours_accrual = monthly_rol_hours_accrual
    if monthly_permit_hours_accrual is not None:
        if monthly_permit_hours_accrual < 0 or monthly_permit_hours_accrual > 200:
            raise HTTPException(400, "monthly_permit_hours_accrual fuori range [0..200]")
        p.monthly_permit_hours_accrual = monthly_permit_hours_accrual
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


# ── Multi-preset WorkingHoursPolicy (α.172.32 B) ──────────────

@router.post("/api/working-hours")
async def create_working_hours_policy(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Crea nuovo preset WorkingHoursPolicy con valori default sensati.
    Editing via PUT successivo."""
    from app.services.rbac import current_user_optional, can_edit_settings
    user = current_user_optional(request)
    if not can_edit_settings(user):
        raise HTTPException(403, "Solo manager+ possono creare orari lavorativi")
    name = name.strip()[:80]
    if not name:
        raise HTTPException(422, "Nome obbligatorio")
    existing = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
        WorkingHoursPolicy.name == name,
    ).first()
    if existing:
        raise HTTPException(409, f"Esiste già una policy con nome '{name}'")
    p = WorkingHoursPolicy(
        tenant_id=CURRENT_TENANT_FALLBACK,
        name=name,
        is_default=False,
        morning_start=time(9, 0), morning_end=time(13, 0),
        afternoon_start=time(14, 0), afternoon_end=time(18, 0),
        working_days=31,
        holidays_country="IT",
        daily_hours_threshold=8.0, weekly_hours_threshold=40.0,
        overtime_multiplier=1.30, night_multiplier=1.25,
        sunday_multiplier=1.50, holiday_multiplier=2.00,
        permit_multiplier=1.0,
        night_start=time(22, 0), night_end=time(6, 0),
        annual_leave_days_default=26.0,
        monthly_rol_hours_accrual=8.0,
        monthly_permit_hours_accrual=8.0,
    )
    db.add(p); db.commit(); db.refresh(p)
    return _serialize_policy(p)


@router.delete("/api/working-hours/{policy_id}")
async def delete_working_hours_policy(
    policy_id: int, request: Request, db: Session = Depends(get_db),
):
    from app.services.rbac import current_user_optional, can_edit_settings
    user = current_user_optional(request)
    if not can_edit_settings(user):
        raise HTTPException(403, "Solo manager+ possono eliminare orari lavorativi")
    p = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.id == policy_id,
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
    ).first()
    if not p:
        raise HTTPException(404, "Policy non trovata")
    if p.is_default:
        raise HTTPException(409, "Non puoi eliminare la policy default. Imposta prima un'altra policy come default.")
    # HARD-BLOCK: blocca delete se assegnata a resource
    used_by = db.query(Resource).filter(
        Resource.working_hours_policy_id == policy_id,
        Resource.tenant_id == CURRENT_TENANT_FALLBACK,
    ).count()
    if used_by:
        raise HTTPException(
            409,
            f"Impossibile eliminare: {used_by} risorse stanno usando questa policy. "
            "Riassegnale a un'altra policy prima di eliminare.",
        )
    # α.172.33.2 — Cascade festività linkate: soft-delete (is_active=False)
    # delle Holiday con scope_policy_id=policy_id. Evita orphan dopo delete.
    affected_holidays = db.query(Holiday).filter(
        Holiday.scope_policy_id == policy_id,
        Holiday.tenant_id == CURRENT_TENANT_FALLBACK,
    ).all()
    for h in affected_holidays:
        h.is_active = False
    db.delete(p); db.commit()
    return {"ok": True, "deactivated_holidays": len(affected_holidays)}


@router.post("/api/working-hours/{policy_id}/set-default")
async def set_default_working_hours_policy(
    policy_id: int, request: Request, db: Session = Depends(get_db),
):
    """Imposta questa policy come default tenant (e demota la precedente)."""
    from app.services.rbac import current_user_optional, can_edit_settings
    user = current_user_optional(request)
    if not can_edit_settings(user):
        raise HTTPException(403, "Solo manager+ possono impostare la policy default")
    p = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.id == policy_id,
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
    ).first()
    if not p:
        raise HTTPException(404, "Policy non trovata")
    # Demota tutte le altre
    db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
        WorkingHoursPolicy.id != policy_id,
    ).update({WorkingHoursPolicy.is_default: False})
    p.is_default = True
    db.commit(); db.refresh(p)
    return _serialize_policy(p)


@router.post("/api/working-hours/{policy_id}/duplicate")
async def duplicate_working_hours_policy(
    policy_id: int,
    request: Request,
    new_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Clona una policy esistente con un nuovo nome. Util per creare varianti
    di CCNL (es. 'Cinema base' → 'Cinema con scaglioni doppiaggio')."""
    from app.services.rbac import current_user_optional, can_edit_settings
    user = current_user_optional(request)
    if not can_edit_settings(user):
        raise HTTPException(403, "Solo manager+ possono duplicare orari lavorativi")
    src = db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.id == policy_id,
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
    ).first()
    if not src:
        raise HTTPException(404, "Policy sorgente non trovata")
    new_name = new_name.strip()[:80]
    if not new_name:
        raise HTTPException(422, "Nuovo nome obbligatorio")
    if db.query(WorkingHoursPolicy).filter(
        WorkingHoursPolicy.tenant_id == CURRENT_TENANT_FALLBACK,
        WorkingHoursPolicy.name == new_name,
    ).first():
        raise HTTPException(409, f"Esiste già una policy con nome '{new_name}'")
    clone = WorkingHoursPolicy(
        tenant_id=src.tenant_id,
        name=new_name, is_default=False,
        morning_start=src.morning_start, morning_end=src.morning_end,
        afternoon_start=src.afternoon_start, afternoon_end=src.afternoon_end,
        working_days=src.working_days,
        holidays_country=src.holidays_country,
        daily_hours_threshold=src.daily_hours_threshold,
        weekly_hours_threshold=src.weekly_hours_threshold,
        overtime_multiplier=src.overtime_multiplier,
        night_multiplier=src.night_multiplier,
        sunday_multiplier=src.sunday_multiplier,
        holiday_multiplier=src.holiday_multiplier,
        permit_multiplier=src.permit_multiplier,
        night_start=src.night_start, night_end=src.night_end,
        overtime_brackets=list(src.overtime_brackets) if src.overtime_brackets else None,
        ccnl_label=src.ccnl_label,
        annual_leave_days_default=getattr(src, "annual_leave_days_default", 26.0),
        monthly_rol_hours_accrual=getattr(src, "monthly_rol_hours_accrual", 8.0),
        monthly_permit_hours_accrual=getattr(src, "monthly_permit_hours_accrual", 8.0),
    )
    db.add(clone); db.flush()

    # α.172.33.2 — Cascade duplicate festività scope=src → clone.
    # Tenant-wide (scope_policy_id=NULL) NON copiate (sono condivise).
    src_holidays = db.query(Holiday).filter(
        Holiday.scope_policy_id == src.id,
        Holiday.tenant_id == src.tenant_id,
        Holiday.is_active == True,  # noqa: E712
    ).all()
    cloned_holidays = 0
    for sh in src_holidays:
        h = Holiday(
            tenant_id=sh.tenant_id,
            date=sh.date, name=sh.name, kind=sh.kind,
            scope_policy_id=clone.id,
            is_active=True,
            created_by_user_id=user.id if user else None,
        )
        db.add(h)
        cloned_holidays += 1

    db.commit(); db.refresh(clone)
    out = _serialize_policy(clone)
    out["cloned_holidays"] = cloned_holidays
    return out


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
    # v3.5.0-alpha.137 — Valuta base tenant (ISO 4217: EUR/USD/GBP/...)
    default_currency: Optional[str] = Form(None),
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
        # α.137 valuta base
        default_currency=(default_currency.upper().strip() if default_currency else None),
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


# ── Filesystem scan whitelist (tenant-level) — α.105 ──────────────────


@router.get("/api/fs-scan-paths")
async def fs_scan_paths_get(
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Lista path autorizzati per scan filesystem a livello tenant."""
    from app.models import Tenant
    u = _resolve_current_user(db, access_token)
    _require_admin(u)
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    if not t:
        raise HTTPException(404)
    return {"paths": t.fs_scan_allowed_paths or []}


@router.put("/api/fs-scan-paths")
async def fs_scan_paths_set(
    paths_json: str = Form(...),  # JSON array string
    access_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """Setta lista path autorizzati tenant-level. paths_json = JSON array."""
    import json as _json
    from pathlib import Path as _P
    from app.models import Tenant
    u = _resolve_current_user(db, access_token)
    _require_admin(u)
    try:
        paths = _json.loads(paths_json)
    except _json.JSONDecodeError:
        raise HTTPException(400, "paths_json malformato")
    if not isinstance(paths, list):
        raise HTTPException(400, "paths_json deve essere lista")
    # Normalize: assoluti, sanity check
    clean = []
    for p in paths:
        if not isinstance(p, str):
            continue
        ps = p.strip()
        if not ps:
            continue
        # Path traversal guard: niente .. nei path autorizzati
        if ".." in _P(ps).parts:
            raise HTTPException(400, f"Path con '..' non ammesso: {ps}")
        clean.append(ps)
    t = db.query(Tenant).filter(Tenant.id == current_tenant_id()).first()
    if not t:
        raise HTTPException(404)
    t.fs_scan_allowed_paths = clean or None
    db.commit()
    return {"ok": True, "paths": clean}


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


# ── v3.5.0-alpha.112 — Numerazione documenti ──────────────────────────
# CRUD su NumberingConfig per tenant. Lo storico non viene rinumerato:
# le regole influenzano solo gli emessi futuri (quando il numbering
# service verrà cabled in iterazione successiva). Per ora UI + persistenza
# delle regole + endpoint preview format.

NUMBERING_DOC_TYPES = [
    {"key": "quote",                "label": "Quotazioni",            "default": "Q-{YYYY}-{NNN}"},
    {"key": "billing_batch",        "label": "Batch fatturazione",    "default": "BB-{YYYY}-{NNN}"},
    {"key": "invoice",              "label": "Fattura standard",      "default": "{NNN}/{YYYY}"},
    {"key": "invoice_closing",      "label": "Fattura di chiusura",   "default": "CL-{PROJECT_CODE}-{YYYY}"},
    {"key": "invoice_credit_note",  "label": "Nota di credito (TD04)","default": "NC-{YYYY}-{NNN}"},
    {"key": "job",                  "label": "Job",                   "default": "{PROJECT_CODE}-J{NNN}"},
    {"key": "cost_report_export",   "label": "Export Cost Report",    "default": "CR-{PROJECT_CODE}-{YYYYMMDD}"},
    {"key": "supplier_invoice",     "label": "Fattura passiva",       "default": "FP-{YYYY}-{NNN}"},
    # v3.5.0-alpha.116 — spese aziendali + logistica fisica
    {"key": "overhead_cost",        "label": "Spese aziendali (overhead)", "default": "OH-{YYYY}-{NNNN}"},
    {"key": "ingest_batch",         "label": "Batch ingest fisico",   "default": "BATCH-{YYYY}-{NNN}"},
    {"key": "ddt",                  "label": "DDT spedizione",        "default": "DDT-{YYYY}-{NNN}"},
]

NUMBERING_VARS = [
    {"v": "{YYYY}",           "desc": "Anno 4 cifre (2026)"},
    {"v": "{YY}",             "desc": "Anno 2 cifre (26)"},
    {"v": "{MM}",             "desc": "Mese 2 cifre (05)"},
    {"v": "{DD}",             "desc": "Giorno 2 cifre (15)"},
    {"v": "{YYYYMMDD}",       "desc": "Data compatta (20260515)"},
    {"v": "{NNN}",            "desc": "Progressivo 3 cifre (001)"},
    {"v": "{NN}",             "desc": "Progressivo 2 cifre (01)"},
    {"v": "{NNNN}",           "desc": "Progressivo 4 cifre (0001)"},
    {"v": "{PROJECT_CODE}",   "desc": "Codice progetto (se applicabile)"},
    {"v": "{CLIENT_CODE}",    "desc": "Codice cliente (se applicabile)"},
]


@router.get("/api/numbering")
async def list_numbering(db: Session = Depends(get_db)):
    """Restituisce configurazione attuale + default per ogni doc_type.
    Se record assenti per tenant, ritorna default come placeholder."""
    from app.models.models import NumberingConfig
    from app.services.numbering import supported_vars
    tid = current_tenant_id()
    existing = {n.doc_type: n for n in db.query(NumberingConfig).filter(
        NumberingConfig.tenant_id == tid
    ).all()}
    rows = []
    for spec in NUMBERING_DOC_TYPES:
        rec = existing.get(spec["key"])
        rows.append({
            "doc_type": spec["key"],
            "label": spec["label"],
            "format_pattern": rec.format_pattern if rec else spec["default"],
            "default_pattern": spec["default"],
            "reset_yearly": rec.reset_yearly if rec else True,
            "current_year": rec.current_year if rec else None,
            "current_seq": rec.current_seq if rec else 0,
            "configured": bool(rec),
            "notes": (rec.notes if rec else None),
            # v3.5.0-alpha.116: variabili supportate per questo doc_type
            "supported_vars": sorted(list(supported_vars(spec["key"]))),
        })
    return {"vars": NUMBERING_VARS, "configs": rows}


@router.put("/api/numbering/{doc_type}")
async def upsert_numbering(
    doc_type: str,
    format_pattern: str = Form(...),
    reset_yearly: bool = Form(True),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    from app.models.models import NumberingConfig
    from app.services.numbering import validate_pattern
    valid = {s["key"] for s in NUMBERING_DOC_TYPES}
    if doc_type not in valid:
        raise HTTPException(400, f"doc_type non valido: {doc_type}")
    if not format_pattern.strip():
        raise HTTPException(400, "format_pattern obbligatorio")
    # v3.5.0-alpha.116: validate variabili supportate per doc_type
    bad_var = validate_pattern(doc_type, format_pattern.strip())
    if bad_var:
        from app.services.numbering import supported_vars
        allowed = sorted(supported_vars(doc_type))
        raise HTTPException(
            400,
            f"Variabile {{{bad_var}}} non supportata per {doc_type}. "
            f"Variabili valide: {', '.join('{'+v+'}' for v in allowed)}."
        )
    # v3.5.0-alpha.118 (audit M4): quote versioning -v2 suffix richiede
    # che il pattern termini con un blocco progressivo numerico chiaro.
    # Senza, il parser tail rsplit("-",1)[1] cerca cifre dopo l'ultimo "-"
    # e fallisce se l'ultimo blocco è {PROJECT_CODE} o testo.
    # Es. "Q-{PROJECT_CODE}-{NNN}" OK (termina in NNN).
    #     "{PROJECT_CODE}-J{NNN}" OK.
    #     "Q-{PROJECT_CODE}" NO (no {NNN/NN/NNNN} finale).
    if doc_type == "quote":
        # accept pattern that ENDS with {NNN}/{NN}/{NNNN}
        import re as _re
        if not _re.search(r"\{N{2,4}\}\s*$", format_pattern.strip()):
            raise HTTPException(
                400,
                f"Per quote il pattern DEVE terminare con un blocco progressivo "
                f"({{NNN}}/{{NN}}/{{NNNN}}) per supportare il versioning -v2/-v3. "
                f"Pattern attuale: {format_pattern.strip()}"
            )
    tid = current_tenant_id()
    rec = db.query(NumberingConfig).filter(
        NumberingConfig.tenant_id == tid,
        NumberingConfig.doc_type == doc_type,
    ).first()
    if rec is None:
        rec = NumberingConfig(tenant_id=tid, doc_type=doc_type)
        db.add(rec)
    rec.format_pattern = format_pattern.strip()
    rec.reset_yearly = bool(reset_yearly)
    rec.notes = notes
    db.commit()
    db.refresh(rec)
    return {"ok": True, "doc_type": rec.doc_type, "format_pattern": rec.format_pattern}


@router.post("/api/numbering/{doc_type}/preview")
async def preview_numbering(
    doc_type: str,
    project_code: Optional[str] = Form(None),
    client_code: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Renderizza il prossimo codice secondo il format corrente — solo preview."""
    from app.models.models import NumberingConfig
    from datetime import date
    tid = current_tenant_id()
    spec = next((s for s in NUMBERING_DOC_TYPES if s["key"] == doc_type), None)
    if not spec:
        raise HTTPException(400, "doc_type non valido")
    rec = db.query(NumberingConfig).filter(
        NumberingConfig.tenant_id == tid,
        NumberingConfig.doc_type == doc_type,
    ).first()
    fmt = (rec.format_pattern if rec else spec["default"])
    seq = ((rec.current_seq if rec else 0) or 0) + 1
    today = date.today()
    # v3.5.0-alpha.118: placeholder esplicito tra «...» così user vede che è
    # un valore esempio (non un vero codice progetto/cliente).
    used_proj_placeholder = not project_code
    used_cli_placeholder = not client_code
    out = (
        fmt.replace("{YYYY}", f"{today.year:04d}")
           .replace("{YY}",   f"{today.year % 100:02d}")
           .replace("{MM}",   f"{today.month:02d}")
           .replace("{DD}",   f"{today.day:02d}")
           .replace("{YYYYMMDD}", today.strftime("%Y%m%d"))
           .replace("{NNNN}", f"{seq:04d}")
           .replace("{NNN}",  f"{seq:03d}")
           .replace("{NN}",   f"{seq:02d}")
           .replace("{PROJECT_CODE}", (project_code or "«PROJ»"))
           .replace("{CLIENT_CODE}",  (client_code or "«CLI»"))
    )
    return {
        "preview": out,
        "format": fmt,
        "next_seq": seq,
        "uses_placeholder": used_proj_placeholder or used_cli_placeholder,
        "placeholder_note": (
            "I valori «PROJ»/«CLI» sono placeholder esempio: al momento "
            "della creazione del documento saranno sostituiti dai codici "
            "reali progetto/cliente."
            if (used_proj_placeholder or used_cli_placeholder) else None
        ),
    }
