"""MediaFlow v3 — entrypoint FastAPI con AI e gerarchia Client→Project→Quote."""
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
from pathlib import Path
from app.config import settings
from app.database import create_tables
from app.routers import (
    auth, resources, planning, finance, dam,
    pricelist, quotes, cost_report as cr,
    clients, projects, ai, departments, settings as settings_router,
    assignments, hr, jobs,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "assets").mkdir(exist_ok=True)
    (settings.upload_dir / "thumbnails").mkdir(exist_ok=True)
    yield


app = FastAPI(title="MediaFlow", version="3.4.21.1", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# Middleware: forza no-cache sulle risposte HTML.
# Risolve il caso in cui il browser serve il template vecchio dopo un deploy.
# Gli static (/static/*) restano cacheabili, hanno query string ?v=X.Y.Z per il bust.
@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


# ── Auth guard (v3.4.21.1.1) ─────────────────────────────────────
# Redirect a /auth/login se cookie access_token mancante/invalido per
# pagine HTML. API (path /api/* o accept JSON) ricevono 401 JSON.
PUBLIC_PATHS = ("/auth/", "/static/", "/health", "/docs", "/openapi.json", "/favicon.ico", "/redoc")


def _resolve_user_from_token(token: str):
    """Apre una sessione DB minima e ritorna l'utente. None se token invalido o utente disabilitato."""
    if not token:
        return None
    from app.services.auth import decode_token
    payload = decode_token(token)
    if not payload:
        return None
    email = payload.get("sub")
    if not email:
        return None
    from app.database import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email == email, User.is_active == True).first()  # noqa: E712
    finally:
        db.close()


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    request.state.current_user = None

    user = _resolve_user_from_token(request.cookies.get("access_token"))
    request.state.current_user = user

    if any(path == p.rstrip("/") or path.startswith(p) for p in PUBLIC_PATHS):
        return await call_next(request)

    if not user:
        return _unauthorized(request, path)

    return await call_next(request)


def _unauthorized(request: Request, path: str):
    accept = request.headers.get("accept", "")
    is_api = path.startswith("/api/") or "/api/" in path or "application/json" in accept
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Non autenticato"}, status_code=401)
    next_url = path
    if request.url.query:
        next_url += f"?{request.url.query}"
    return RedirectResponse(url=f"/auth/login?next={next_url}", status_code=303)

app.include_router(auth.router)
app.include_router(clients.router)
app.include_router(projects.router)
app.include_router(resources.router)
app.include_router(planning.router)
app.include_router(finance.router)
app.include_router(dam.router)
app.include_router(pricelist.router)
app.include_router(quotes.router)
app.include_router(cr.router)
app.include_router(ai.router)
app.include_router(departments.router)
app.include_router(settings_router.router)
app.include_router(assignments.router)
app.include_router(hr.router)
app.include_router(jobs.router)


@app.get("/", response_class=HTMLResponse)
async def root(): return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    from app.services.ai_provider import get_provider
    return templates.TemplateResponse(
        "pages/dashboard.html",
        {"request": request, "ai_enabled": get_provider() is not None},
    )


@app.get("/health")
async def health():
    from app.services.ai_provider import get_provider
    p = get_provider()
    return {"status": "ok", "app": settings.app_name, "version": "3.4.21.1",
            "ai": {"configured": p is not None, "provider": p.name if p else None}}
