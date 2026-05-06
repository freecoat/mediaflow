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
    hr, jobs, admin, notifications as notifications_router,
    tech_sheets, team,
)


def _auto_migrate_columns():
    """Auto-fix difensivo per colonne aggiunte di recente al modello.

    Idempotente. Evita crash se l'utente ha pull-ato il codice senza
    eseguire la migrazione corrispondente (caso reale single-user dev DB).
    Per cambi maggiori (nuove tabelle, FK pesanti) preferisci sempre lo
    script `scripts/migrate_*.py` esplicito. Le NUOVE tabelle introdotte
    da Base.metadata.create_all() vengono create automaticamente da
    create_tables() prima di questa funzione.
    """
    from sqlalchemy import inspect, text
    from app.database import engine
    insp = inspect(engine)
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "extra_permissions" not in cols:
            print("[auto-migrate] users.extra_permissions mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN extra_permissions TEXT NULL"))
    # v3.4.32 — Booking esecutivo (priority/execution_status/overtime_status/...)
    if "bookings" in insp.get_table_names():
        bcols = {c["name"] for c in insp.get_columns("bookings")}
        booking_alter = [
            ("priority", "VARCHAR(16) NOT NULL DEFAULT 'normal'"),
            ("execution_status", "VARCHAR(16) NOT NULL DEFAULT 'planned'"),
            ("not_done_reason", "TEXT NULL"),
            ("count_in_costs", "BOOLEAN NOT NULL DEFAULT 0"),
            ("overtime_status", "VARCHAR(16) NOT NULL DEFAULT 'none'"),
            ("original_end_datetime", "DATETIME NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in booking_alter:
                if col not in bcols:
                    print(f"[auto-migrate] bookings.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {ddl}"))
    # v3.4.32.2 — WorkingHoursPolicy: overtime_brackets JSON + ccnl_label
    if "working_hours_policies" in insp.get_table_names():
        wcols = {c["name"] for c in insp.get_columns("working_hours_policies")}
        whp_alter = [
            ("overtime_brackets", "TEXT NULL"),
            ("ccnl_label", "VARCHAR(120) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in whp_alter:
                if col not in wcols:
                    print(f"[auto-migrate] working_hours_policies.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE working_hours_policies ADD COLUMN {col} {ddl}"))
    # v3.4.34 — Quote: category_order JSON nullable
    if "quotes" in insp.get_table_names():
        qcols = {c["name"] for c in insp.get_columns("quotes")}
        if "category_order" not in qcols:
            print("[auto-migrate] quotes.category_order mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE quotes ADD COLUMN category_order TEXT NULL"))
        # v3.4.50.1 — Versioning quote
        quote_alter = [
            ("parent_quote_id", "INTEGER NULL REFERENCES quotes(id)"),
            ("superseded_by_id", "INTEGER NULL REFERENCES quotes(id)"),
            # v3.4.52 — phantom quote (reverse-flow)
            ("is_phantom", "BOOLEAN NOT NULL DEFAULT 0"),
        ]
        with engine.begin() as conn:
            for col, ddl in quote_alter:
                if col not in qcols:
                    print(f"[auto-migrate] quotes.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE quotes ADD COLUMN {col} {ddl}"))
    # v3.4.50.1 — QuoteLine: parent_line_id per eredità righe in versioning
    # v3.5.0-alpha.27 — QuoteLine: is_optional + section_label
    if "quote_lines" in insp.get_table_names():
        qlcols = {c["name"] for c in insp.get_columns("quote_lines")}
        ql_alter = [
            ("parent_line_id", "INTEGER NULL REFERENCES quote_lines(id)"),
            ("is_optional", "BOOLEAN NOT NULL DEFAULT 0"),
            ("section_label", "VARCHAR(120) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in ql_alter:
                if col not in qlcols:
                    print(f"[auto-migrate] quote_lines.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE quote_lines ADD COLUMN {col} {ddl}"))
    # v3.5.0 — AI tool-use nativo: stato del loop su conversazione + binding
    # tool_use_id ↔ AIAction per riprendere il loop dopo Apply.
    if "ai_conversations" in insp.get_table_names():
        accols = {c["name"] for c in insp.get_columns("ai_conversations")}
        if "tool_state" not in accols:
            print("[auto-migrate] ai_conversations.tool_state mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE ai_conversations ADD COLUMN tool_state TEXT NULL"))
    if "ai_actions" in insp.get_table_names():
        aacols = {c["name"] for c in insp.get_columns("ai_actions")}
        if "tool_use_id" not in aacols:
            print("[auto-migrate] ai_actions.tool_use_id mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE ai_actions ADD COLUMN tool_use_id VARCHAR(128) NULL"))
    # v3.5.0-alpha.22 — TimePunch.break_minutes (pausa pranzo opzionale)
    if "time_punches" in insp.get_table_names():
        tpcols = {c["name"] for c in insp.get_columns("time_punches")}
        if "break_minutes" not in tpcols:
            print("[auto-migrate] time_punches.break_minutes mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE time_punches ADD COLUMN break_minutes "
                    "INTEGER NOT NULL DEFAULT 0"))
    # v3.5.0-alpha.7 — Soft-delete cestino: deleted_at + deleted_by_user_id
    # su Quote. v3.5.0-alpha.8 estende a Project.
    soft_alter = [
        ("deleted_at",         "DATETIME NULL"),
        ("deleted_by_user_id", "INTEGER NULL REFERENCES users(id)"),
    ]
    for table_name in ("quotes", "projects"):
        if table_name not in insp.get_table_names():
            continue
        cols = {c["name"] for c in insp.get_columns(table_name)}
        with engine.begin() as conn:
            for col, ddl in soft_alter:
                if col not in cols:
                    print(f"[auto-migrate] {table_name}.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col} {ddl}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    # Auto-fix colonne aggiunte di recente (v3.4.27.1) — evita crash se
    # l'utente ha pull-ato senza lanciare la migrazione [K]
    try:
        _auto_migrate_columns()
    except Exception as e:
        print(f"[lifespan] _auto_migrate_columns failed: {e}")
    # v3.5.0-alpha.7 — Registra event listener per soft-delete (Quote).
    # Filtra automaticamente i record con deleted_at != NULL su tutte le
    # query SELECT, salvo execution_options(include_deleted=True).
    try:
        from app.services.soft_delete import _install_soft_delete_filter
        _install_soft_delete_filter()
    except Exception as e:
        print(f"[lifespan] soft-delete listener init failed: {e}")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / "assets").mkdir(exist_ok=True)
    (settings.upload_dir / "thumbnails").mkdir(exist_ok=True)
    # Bootstrap ruoli built-in (v3.4.27)
    try:
        from app.database import SessionLocal
        from app.services.rbac import ensure_built_in_roles
        _db = SessionLocal()
        try:
            ensure_built_in_roles(_db)
        finally:
            _db.close()
    except Exception as e:
        print(f"[lifespan] ensure_built_in_roles failed: {e}")
    # Check deadline job al boot (v3.4.28) — emette notifiche per job con
    # end_date imminente, idempotente (dedup 14 giorni)
    try:
        from app.database import SessionLocal
        from app.services.job_deadline_check import check_job_deadlines
        _db = SessionLocal()
        try:
            n = check_job_deadlines(_db)
            if n:
                print(f"[lifespan] check_job_deadlines: {n} notifiche emesse")
        finally:
            _db.close()
    except Exception as e:
        print(f"[lifespan] check_job_deadlines failed: {e}")
    yield


app = FastAPI(title="MediaFlow", version="3.5.0-alpha.27", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Espone helpers RBAC ai template Jinja per condizionali UI
from app.services import rbac as _rbac
templates.env.globals["is_admin"] = _rbac.is_admin
templates.env.globals["is_manager"] = _rbac.is_manager
templates.env.globals["is_producer"] = _rbac.is_producer
templates.env.globals["is_staff"] = _rbac.is_staff
templates.env.globals["is_elevated"] = _rbac.is_elevated
templates.env.globals["can_view_finance"] = _rbac.can_view_finance
templates.env.globals["can_edit_cost_actuals"] = _rbac.can_edit_cost_actuals
templates.env.globals["can_edit_settings"] = _rbac.can_edit_settings
templates.env.globals["can_view_settings"] = _rbac.can_view_settings
templates.env.globals["can_edit_pricelist"] = _rbac.can_edit_pricelist
templates.env.globals["can_assign_resources"] = _rbac.can_assign_resources
templates.env.globals["can_create_booking"] = _rbac.can_create_booking
templates.env.globals["can_approve_unavailability"] = _rbac.can_approve_unavailability
templates.env.globals["can_manage_users"] = _rbac.can_manage_users
templates.env.globals["can_manage_roles"] = _rbac.can_manage_roles
templates.env.globals["has_permission"] = _rbac.has_permission


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


# ── Auth guard (v3.4.27.1) ─────────────────────────────────────
# Redirect a /auth/login se cookie access_token mancante/invalido per
# pagine HTML. API (path /api/* o accept JSON) ricevono 401 JSON.
PUBLIC_PATHS = ("/auth/", "/static/", "/health", "/docs", "/openapi.json", "/favicon.ico", "/redoc", "/public/")


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
    from sqlalchemy.orm import joinedload
    db = SessionLocal()
    try:
        u = db.query(User).options(joinedload(User.role_obj)).filter(
            User.email == email, User.is_active == True  # noqa: E712
        ).first()
        if u:
            # Forza il caricamento dei permessi prima del detach
            _ = u.role_obj.permissions if u.role_obj else None
        return u
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

    # ── RBAC: blacklist path/prefix per ruolo ────────────────────
    forbidden = _is_forbidden_for_role(path, user)
    if forbidden:
        return _forbidden(request, path)

    return await call_next(request)


# Path/prefix vietati a staff/viewer (non vedono finanza, listino, quote, settings, reparti).
# I router HR e planning gestiscono internamente lo scoping fine (vedi rbac.scope_resource_id).
_FINANCE_BLOCKED_PREFIXES = ("/quotes", "/cost-report", "/finance", "/pricelist", "/clients")
_NON_ELEVATED_BLOCKED_PREFIXES = ("/resources",)  # anagrafica risorse globale
_ADMIN_ONLY_PREFIXES = ("/departments", "/settings/api/working-hours", "/settings/api/ai")


def _is_forbidden_for_role(path: str, user) -> bool:
    from app.services.rbac import is_admin, is_elevated, can_view_finance
    # Staff/viewer: niente finanza/quote/listino/clienti
    if not can_view_finance(user):
        for pref in _FINANCE_BLOCKED_PREFIXES:
            if path == pref or path.startswith(pref + "/"):
                return True
    # Staff/viewer: niente anagrafica risorse globale
    if not is_elevated(user):
        for pref in _NON_ELEVATED_BLOCKED_PREFIXES:
            if path == pref or path.startswith(pref + "/"):
                return True
    # Solo admin tocca le impostazioni globali (orari, AI, reparti)
    if not is_admin(user):
        for pref in _ADMIN_ONLY_PREFIXES:
            if path == pref or path.startswith(pref + "/"):
                return True
    return False


def _forbidden(request: Request, path: str):
    accept = request.headers.get("accept", "")
    is_api = path.startswith("/api/") or "/api/" in path or "application/json" in accept
    if is_api:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Accesso non autorizzato per questo ruolo"}, status_code=403)
    from fastapi.responses import HTMLResponse
    # NB: body globale (main.css) ha `display:flex; min-height:100vh;` per il
    # layout sidebar+content. Sulla pagina 403 stand-alone forziamo `display:block`
    # e centriamo il contenuto con `margin:0 auto + max-width`. Senza l'override
    # il flex-row del body tiene il contenitore inerte a sinistra.
    html = """<!DOCTYPE html><html lang="it"><head><meta charset="utf-8">
<title>403 — Accesso negato</title><link rel="stylesheet" href="/static/css/main.css"></head>
<body style="display:block;">
<div style="min-height:100vh;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:16px;padding:24px;text-align:center;width:100%;box-sizing:border-box;">
<div style="font-size:64px;">🔒</div>
<h1 style="margin:0;font-size:24px;">Accesso negato</h1>
<p style="color:var(--text2);max-width:480px;">Il tuo ruolo non ha i permessi per accedere a questa sezione.</p>
<a href="/dashboard" class="btn btn-primary">Torna alla Dashboard</a>
</div></body></html>"""
    return HTMLResponse(html, status_code=403)


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
app.include_router(hr.router)
app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(notifications_router.router)
app.include_router(tech_sheets.router)
app.include_router(team.router)


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
    return {"status": "ok", "app": settings.app_name, "version": app.version,
            "ai": {"configured": p is not None, "provider": p.name if p else None}}
