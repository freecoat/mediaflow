"""Router autenticazione — login, logout, profilo utente, MFA TOTP (v3.5.0-alpha.70.4)."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.auth import authenticate_user, create_access_token, hash_password
from app.services.rbac import current_user_optional, current_user
from app.models import User, UserRole
from app.config import settings
import base64

router = APIRouter(prefix="/auth", tags=["auth"])


# v3.5.0-alpha.70.4 — token "pending MFA" temporaneo per il flow 2-step.
# Cookie short-lived (10 min) usato per identificare l'user che ha già
# superato la password ma deve ancora fornire OTP. Mai contiene token
# di accesso completo.
MFA_PENDING_COOKIE = "mfa_pending"
MFA_PENDING_MAX_AGE = 10 * 60


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next_url: str = Query("/dashboard", alias="next")):
    from app.main import templates
    return templates.TemplateResponse("pages/login.html", {"request": request, "next": next_url})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    from app.main import templates
    # Leggiamo `next` direttamente dal form: in FastAPI usare Form(alias="next")
    # con un parametro Python rinominato non sempre funziona se il nome desiderato
    # collide con un builtin. Il path è pochi byte di body, lo prendiamo a mano.
    form = await request.form()
    next_url = (form.get("next") or "/dashboard").strip()

    # v3.5.0-alpha.101 R-MT1 — Scope autenticazione al tenant corrente
    # (dal subdomain/host resolved dal middleware). Se 2 user con stessa
    # email su tenant diversi, solo quello del tenant corrente passa.
    request_tid = getattr(request.state, "tenant_id", None)
    user = authenticate_user(db, email, password, tenant_id=request_tid)
    if not user:
        return templates.TemplateResponse(
            "pages/login.html",
            {"request": request, "error": "Email o password non corretti", "next": next_url, "email": email},
            status_code=401,
        )
    target = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    # v3.5.0-alpha.70.4 — MFA TOTP gate. Se user.mfa_enabled, password OK
    # apre uno step intermedio: cookie "mfa_pending" con email (short-lived)
    # → redirect a /auth/mfa-challenge. NON setta access_token finché OTP OK.
    if user.mfa_enabled:
        pending_token = create_access_token({
            "sub": user.email, "tid": user.tenant_id, "mfa_pending": True,
        })
        resp = RedirectResponse(
            url=f"/auth/mfa-challenge?next={target}", status_code=303
        )
        resp.set_cookie(
            key=MFA_PENDING_COOKIE,
            value=pending_token,
            httponly=True,
            max_age=MFA_PENDING_MAX_AGE,
            samesite="lax",
        )
        return resp
    # v3.5.0-alpha.101 — JWT include tid (tenant_id) per cross-tenant gate.
    token = create_access_token({"sub": user.email, "tid": user.tenant_id})
    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
        samesite="lax",
    )
    # v3.5.0-alpha.78.1 — TPN audit log login (admin compreso)
    try:
        from app.services.project_access import log_asset_access
        from app.models import AssetAccessAction
        log_asset_access(db, user=user, action=AssetAccessAction.view,
                         request=request, extra=f"login email={user.email}")
    except Exception:
        pass
    return resp


# ── MFA TOTP (v3.5.0-alpha.70.4) ──────────────────────────────────────

def _resolve_mfa_pending_user(request: Request, db: Session) -> User:
    """Decodifica cookie mfa_pending e ritorna l'user. 403 se invalido."""
    from app.services.auth import decode_token
    token = request.cookies.get(MFA_PENDING_COOKIE)
    if not token:
        raise HTTPException(401, "Nessun pending MFA")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Token MFA pending invalido")
    if not payload.get("mfa_pending"):
        raise HTTPException(401, "Token non è di tipo MFA pending")
    email = payload.get("sub")
    if not email:
        raise HTTPException(401, "Token MFA pending senza sub")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(401, "User non trovato")
    return user


@router.get("/mfa-challenge", response_class=HTMLResponse)
async def mfa_challenge_page(
    request: Request,
    next_url: str = Query("/dashboard", alias="next"),
    db: Session = Depends(get_db),
):
    from app.main import templates
    try:
        user = _resolve_mfa_pending_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/auth/login", status_code=303)
    return templates.TemplateResponse(
        "pages/mfa_challenge.html",
        {"request": request, "next": next_url, "email": user.email},
    )


@router.post("/mfa-verify")
async def mfa_verify(
    request: Request,
    otp: str = Form(...),
    db: Session = Depends(get_db),
):
    from app.main import templates
    form = await request.form()
    next_url = (form.get("next") or "/dashboard").strip()
    try:
        user = _resolve_mfa_pending_user(request, db)
    except HTTPException:
        return RedirectResponse(url="/auth/login", status_code=303)
    from app.services.mfa import verify_user_otp
    if not verify_user_otp(user, otp):
        return templates.TemplateResponse(
            "pages/mfa_challenge.html",
            {"request": request, "next": next_url, "email": user.email,
             "error": "Codice OTP non valido"},
            status_code=401,
        )
    # OTP OK → emit access_token, clear pending cookie
    target = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    token = create_access_token({"sub": user.email})
    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
        samesite="lax",
    )
    resp.delete_cookie(MFA_PENDING_COOKIE)
    return resp


@router.get("/api/mfa/status")
async def mfa_status(request: Request, user: User = Depends(current_user)):
    return {
        "mfa_enabled": bool(user.mfa_enabled),
        "mfa_enabled_at": (
            str(user.mfa_enabled_at)[:19] if user.mfa_enabled_at else None
        ),
        "has_pending_secret": bool(
            user.mfa_secret_encrypted and not user.mfa_enabled
        ),
    }


@router.post("/api/mfa/setup")
async def mfa_setup(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Genera nuovo secret + QR. Salva encrypted ma mfa_enabled=False
    finché verify-setup non riesce. Se già enabled, 409 (disabilita prima)."""
    if user.mfa_enabled:
        raise HTTPException(409, "MFA già attivo. Disattivalo prima per rigenerare.")
    from app.services.mfa import setup_user_mfa
    secret, png_bytes, uri = setup_user_mfa(user)
    db.commit()
    return {
        "secret": secret,  # mostrato all'utente per fallback manuale
        "qr_png_base64": base64.b64encode(png_bytes).decode("ascii"),
        "provisioning_uri": uri,
    }


@router.post("/api/mfa/verify-setup")
async def mfa_verify_setup(
    otp: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Verifica primo OTP. Se OK → mfa_enabled=True."""
    if user.mfa_enabled:
        return {"ok": True, "already_enabled": True}
    from app.services.mfa import confirm_setup
    if not confirm_setup(user, otp):
        raise HTTPException(400, "Codice OTP non valido")
    db.commit()
    return {"ok": True, "mfa_enabled": True}


@router.post("/api/mfa/disable")
async def mfa_disable(
    otp: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Disabilita MFA. Richiede OTP attivo per conferma."""
    if not user.mfa_enabled:
        return {"ok": True, "not_enabled": True}
    from app.services.mfa import disable_mfa as _disable
    if not _disable(user, otp):
        raise HTTPException(400, "Codice OTP non valido")
    db.commit()
    return {"ok": True, "mfa_enabled": False}


@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/auth/login", status_code=303)
    resp.delete_cookie("access_token")
    return resp


# ── API JSON ──────────────────────────────────────────────────────────

@router.post("/api/users", tags=["users"])
async def create_user(
    email: str = Form(...),
    full_name: str = Form(...),
    password: str = Form(...),
    role: UserRole = Form(UserRole.staff),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email già registrata")
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email, "role": user.role}
