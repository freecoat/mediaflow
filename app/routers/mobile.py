"""Area mobile /m — PWA companion staff (v3.5.0-alpha.172.158).

Template lean (templates/mobile/), riusa gli endpoint JSON esistenti via fetch.
Auth: il middleware globale (main.py) protegge già /m/* (redirect /auth/login).
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.services.rbac import current_user_optional

router = APIRouter(prefix="/m", tags=["mobile"])


def _tpl():
    from app.main import templates
    return templates


def _page(request, name, **ctx):
    user = current_user_optional(request)
    return _tpl().TemplateResponse(
        f"mobile/{name}.html",
        {"request": request, "user": user, **ctx},
    )


# Pagine HTML (non API): escluse dallo schema OpenAPI. La route a path "" con
# response_class rompeva get_openapi (AssertionError "A response class is needed").
@router.get("", response_class=HTMLResponse, include_in_schema=False)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def m_oggi(request: Request, db: Session = Depends(get_db)):
    return _page(request, "oggi", active="oggi")


@router.get("/timbra", response_class=HTMLResponse, include_in_schema=False)
async def m_timbra(request: Request):
    return _page(request, "timbra", active="timbra")


@router.get("/assegnazioni", response_class=HTMLResponse, include_in_schema=False)
async def m_assegnazioni(request: Request):
    return _page(request, "assegnazioni", active="assegnazioni")


@router.get("/ferie", response_class=HTMLResponse, include_in_schema=False)
async def m_ferie(request: Request):
    return _page(request, "ferie", active="ferie")


@router.get("/notifiche", response_class=HTMLResponse, include_in_schema=False)
async def m_notifiche(request: Request):
    return _page(request, "notifiche", active="notifiche")


@router.get("/offline", response_class=HTMLResponse, include_in_schema=False)
async def m_offline(request: Request):
    return _tpl().TemplateResponse("mobile/offline.html", {"request": request})
