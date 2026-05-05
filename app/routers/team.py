"""
Router /team — pagina unificata Risorse + Reparti (v3.5.0-alpha.21).

Pre-alpha.21: 2 pagine separate (`/resources` lista flat, `/departments` lista
reparti). A 500 risorse / 30 reparti la lista flat diventa muro e i reparti
sono gestionali, non navigabili.

Alpha.21: pagina `/team` con sidebar reparti drill-down + main pane risorse del
reparto selezionato. Backed da endpoint esistenti `/resources/api` +
`/departments/api` (niente nuovi endpoint richiesti). Le 2 pagine vecchie
restano disponibili come accesso amministrativo.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Department


router = APIRouter(prefix="/team", tags=["team"])

CURRENT_TENANT = 1


def _tpl():
    from app.main import templates
    return templates


@router.get("/", response_class=HTMLResponse)
async def team_page(request: Request, db: Session = Depends(get_db)):
    departments = (
        db.query(Department)
        .filter(Department.tenant_id == CURRENT_TENANT, Department.is_active == True)  # noqa: E712
        .order_by(Department.name)
        .all()
    )
    return _tpl().TemplateResponse(
        "pages/team.html",
        {"request": request, "departments": departments},
    )
