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
from app.models import User
from app.models.models import UserAISettings
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
