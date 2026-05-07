"""
Router Manuale d'uso (v3.5.0-alpha.43).

Pagina /manuale: wiki interna con TOC laterale + sezioni con anchor.
Contenuti statici nel template `pages/manuale.html`. Quando i contenuti
crescono si potrà splittare in sezioni multiple o passare a markdown
renderizzato server-side.

Niente API JSON: lettura pura, autenticazione via middleware (qualunque
utente loggato può consultare).
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/manuale", tags=["help"])


def _tpl():
    from app.main import templates
    return templates


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def manuale_page(request: Request):
    return _tpl().TemplateResponse(
        "pages/manuale.html",
        {"request": request, "active_page": "manuale"},
    )
