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
    assignments,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "assets").mkdir(exist_ok=True)
    (settings.upload_dir / "thumbnails").mkdir(exist_ok=True)
    yield


app = FastAPI(title="MediaFlow", version="3.4.6", lifespan=lifespan)

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
    return {"status": "ok", "app": settings.app_name, "version": "3.4.6",
            "ai": {"configured": p is not None, "provider": p.name if p else None}}
