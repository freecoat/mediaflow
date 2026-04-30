"""Router autenticazione — login, logout, profilo utente."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.auth import authenticate_user, create_access_token, hash_password
from app.models import User, UserRole
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


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

    user = authenticate_user(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "pages/login.html",
            {"request": request, "error": "Email o password non corretti", "next": next_url, "email": email},
            status_code=401,
        )
    token = create_access_token({"sub": user.email})
    target = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/dashboard"
    resp = RedirectResponse(url=target, status_code=303)
    resp.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=settings.access_token_expire_minutes * 60,
        samesite="lax",
    )
    return resp


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
