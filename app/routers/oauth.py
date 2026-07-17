"""Router OAuth — v3.5.0-alpha.152.

Flow Authorization Code per Google + Microsoft. UI redirect-based.

Endpoint:
- GET /auth/oauth/{provider}/start — redirect a authorization URL del provider
- GET /auth/oauth/{provider}/callback — callback OAuth + salva token
- GET /auth/oauth/status — JSON status providers + connessioni utente corrente
- POST /auth/oauth/{provider}/disconnect — revoca token
"""
from __future__ import annotations

import html
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import oauth_providers as oauth
from app.services.rbac import current_user_optional

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/oauth", tags=["oauth"])



@router.get("/status")
async def oauth_status(request: Request, db: Session = Depends(get_db)):
    """Stato OAuth: providers configurati + connessioni utente corrente."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta")
    out = {"providers": {}}
    for pid, cfg in oauth.PROVIDERS.items():
        token = oauth.get_token(db, user.id, pid)
        out["providers"][pid] = {
            "label": cfg["label"],
            "configured": oauth.is_configured(pid),
            "connected": bool(token),
            "account_email": token.account_email if token else None,
            "expires_at": token.expires_at.isoformat() if token and token.expires_at else None,
            "scopes": token.scopes if token else None,
            "auto_sync_calendar": bool(token.auto_sync_calendar) if token else False,
            "claqo_calendar_id": token.claqo_calendar_id if token else None,
        }
    return out


@router.get("/{provider}/start")
async def oauth_start(provider: str, request: Request, scopes: Optional[str] = None,
                      db: Session = Depends(get_db)):
    """Inizio flow OAuth: genera state CSRF + redirect a auth URL.
    Opt-in incrementali (in aggiunta al bundle base, mai al posto):
    `scopes=email` → scope Gmail; `scopes=calendar_write` → editing eventi Google;
    `scopes=mail_full` → elimina-definitivo/svuota-cestino email."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta")
    if provider not in oauth.PROVIDERS:
        raise HTTPException(404, f"Provider OAuth sconosciuto: {provider}")
    if not oauth.is_configured(provider):
        raise HTTPException(
            503,
            f"Provider {provider} non configurato (manca {oauth.PROVIDERS[provider]['client_id_env']} "
            f"o {oauth.PROVIDERS[provider]['client_secret_env']} in .env). "
            "Contatta amministratore.")
    extra = None
    if provider == "google" and scopes == "email":
        extra = oauth.GMAIL_SCOPES
    elif provider == "google" and scopes == "calendar_write":
        extra = oauth.CALENDAR_WRITE_SCOPES
    elif provider == "google" and scopes == "mail_full":
        extra = oauth.MAIL_FULL_SCOPES
    state = oauth.make_oauth_state(user.id, provider)
    return RedirectResponse(oauth.authorization_url(provider, state, extra_scopes=extra))


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Callback OAuth: scambia code per token + salva."""
    if error:
        return HTMLResponse(
            f"<h1>OAuth error</h1><p>{html.escape(error)}</p><a href='/settings'>← Torna a impostazioni</a>",
            status_code=400,
        )
    if not code or not state:
        raise HTTPException(400, "Missing code/state")
    parsed = oauth.verify_oauth_state(state)
    if not parsed:
        raise HTTPException(400, "Invalid or expired state (CSRF)")
    if parsed["provider"] != provider:
        raise HTTPException(400, "Provider mismatch")
    user_id = parsed["user_id"]

    # Scambio code → token
    try:
        token_response = oauth.exchange_code_for_token(provider, code)
    except Exception as e:
        log.exception(f"exchange_code_for_token failed: {e}")
        return HTMLResponse(
            f"<h1>OAuth exchange failed</h1><p>{html.escape(str(e))}</p><a href='/settings'>← Torna</a>",
            status_code=502,
        )
    if "access_token" not in token_response:
        return HTMLResponse(
            f"<h1>OAuth error</h1><pre>{html.escape(str(token_response))}</pre><a href='/settings'>← Torna</a>",
            status_code=400,
        )

    # Recupera account_email
    account_email = None
    try:
        info = oauth.fetch_userinfo(provider, token_response["access_token"])
        # Google: info["email"]. Microsoft: info["mail"] o info["userPrincipalName"]
        account_email = info.get("email") or info.get("mail") or info.get("userPrincipalName")
    except Exception as e:
        log.warning(f"fetch_userinfo failed (non-bloccante): {e}")

    oauth.save_token(db, user_id, provider, token_response, account_email=account_email)
    db.commit()

    return HTMLResponse(f"""
        <html><head><meta charset="utf-8"><title>OAuth OK</title></head>
        <body style="font-family:system-ui; padding:40px; text-align:center;">
          <h1>✓ {oauth.PROVIDERS[provider]['label']} collegato</h1>
          <p>Account: <b>{html.escape(str(account_email or '(non rilevato)'))}</b></p>
          <p><a href="/settings">← Torna a impostazioni</a></p>
          <script>setTimeout(() => window.location.href = '/settings', 2000);</script>
        </body></html>
    """)


@router.post("/{provider}/disconnect")
async def oauth_disconnect(provider: str, request: Request, db: Session = Depends(get_db)):
    """Revoca token locale (non chiama revoke al provider — best effort)."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta")
    if provider not in oauth.PROVIDERS:
        raise HTTPException(404, "Provider sconosciuto")
    ok = oauth.revoke_token(db, user.id, provider)
    db.commit()
    return {"ok": ok, "provider": provider}


@router.post("/{provider}/sync-toggle")
async def oauth_sync_toggle(provider: str, request: Request,
                            enabled: bool = Form(...),
                            db: Session = Depends(get_db)):
    """Accende/spegne il push automatico calendario per il provider collegato."""
    user = current_user_optional(request)
    if not user:
        raise HTTPException(401, "Autenticazione richiesta")
    if provider not in oauth.PROVIDERS:
        raise HTTPException(404, "Provider sconosciuto")
    token = oauth.get_token(db, user.id, provider)
    if not token:
        raise HTTPException(404, "Account non collegato")
    token.auto_sync_calendar = bool(enabled)
    db.commit()
    return {"ok": True, "auto_sync_calendar": token.auto_sync_calendar}
