"""
Sincronizzazione automatica Resource → Job (JobResourceAssignment).
v3.4.55.

Regola: ogni booking che cita una risorsa su un job deve garantire che la
risorsa sia anche assegnata al job (`JobResourceAssignment`). Senza questa
relazione il report ore-lavorate-per-risorsa sul progetto non funziona.

Hook in:
- `POST /planning/api/bookings` (forward + reverse, dopo creazione booking)
- `POST /quotes/api/{id}/promote-line-to-cost-line` (booking pre-esistente
  attaccato a quote pending → tira la risorsa anche nel nuovo Job)
- `POST /quotes/api/reverse-attach` (phantom quote + Job → assignment auto)

Idempotente: ritorna l'esistente se già presente.
"""
from typing import Iterable, Optional

from sqlalchemy.orm import Session


def ensure_resource_assigned_to_job(
    db: Session,
    job_id: int,
    resource_id: int,
    *,
    role_in_project: Optional[str] = None,
) -> tuple[object, bool]:
    """Crea JobResourceAssignment(job_id, resource_id) se manca.

    Ritorna `(assignment, created)`. `created=True` se nuovo, False se idempotente.
    `role_in_project` di default = `Resource.role` (es. "Online Editor").
    """
    from app.models import JobResourceAssignment, Resource
    existing = db.query(JobResourceAssignment).filter(
        JobResourceAssignment.job_id == job_id,
        JobResourceAssignment.resource_id == resource_id,
    ).first()
    if existing:
        return existing, False
    res = db.query(Resource).filter(Resource.id == resource_id).first()
    a = JobResourceAssignment(
        job_id=job_id,
        resource_id=resource_id,
        role_in_project=(role_in_project or (res.role if res else None)),
        agreed_daily_rate=(res.daily_rate if res else None),
        agreed_hourly_rate=(res.hourly_rate if res else None),
    )
    db.add(a)
    db.flush()
    return a, True


def ensure_resources_assigned_to_job(
    db: Session,
    job_id: int,
    resource_ids: Iterable[int],
) -> dict:
    """Batch helper: garantisce assignment per tutte le risorse passate.

    Ritorna `{"created": [resource_ids nuove], "existing": [resource_ids già presenti]}`.
    """
    created, existing = [], []
    for rid in set(int(r) for r in resource_ids if r):
        _, was_created = ensure_resource_assigned_to_job(db, job_id, rid)
        (created if was_created else existing).append(rid)
    return {"created": created, "existing": existing}
