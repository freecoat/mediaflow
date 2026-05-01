"""Job deadline check (v3.4.28).

Engine generico per emettere notifiche `job_deadline_approaching` per i job
con `end_date` imminente. Idempotente: per ogni (job_id, threshold) verifica
se esiste già una notifica recente, evita duplicati.

Uso:
- Lifespan startup di `main.py` → check al boot (zero-config).
- Endpoint `POST /admin/api/check-deadlines` → trigger on-demand (admin).
- Cron via `/schedule` (futuro) → check periodico esterno.

Soglie default: 7 giorni e 1 giorno. Notifica chi ha `assign_resources`
(producer/manager/admin/operator → chi gestisce davvero la pianificazione job).
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from app.models import Job, JobStatus, Notification


# Soglie giornaliere (giorni rimanenti alla deadline → severità)
THRESHOLDS = [
    {"days": 1, "severity": "action_required", "label": "domani"},
    {"days": 3, "severity": "action_required", "label": "tra 3 giorni"},
    {"days": 7, "severity": "info", "label": "tra una settimana"},
]

# Stati job che NON ricevono check (già chiusi)
EXCLUDED_STATUSES = {JobStatus.completed, JobStatus.cancelled, JobStatus.invoiced}

# Finestra di dedup: se esiste già una notifica con stesso (job_id, threshold_days)
# emessa da N giorni in qua, non ne emette una nuova.
DEDUP_WINDOW_DAYS = 14


def check_job_deadlines(db: Session, *, tenant_id: int = 1) -> int:
    """Verifica jobs con deadline imminente, emette notifiche idempotenti.

    Ritorna il numero di notifiche emesse (0 se nessuna nuova deadline).
    """
    from app.services import notifications as notif_svc

    today = date.today()
    max_horizon = max(t["days"] for t in THRESHOLDS)
    cutoff_dt = datetime.utcnow() - timedelta(days=DEDUP_WINDOW_DAYS)

    candidates: List[Job] = (
        db.query(Job)
        .filter(
            Job.end_date.isnot(None),
            Job.end_date >= today,
            Job.end_date <= today + timedelta(days=max_horizon),
            Job.status.notin_(EXCLUDED_STATUSES),
        )
        .all()
    )

    emitted = 0
    for job in candidates:
        days_left = (job.end_date - today).days
        # Trova la soglia più restrittiva applicabile (la più piccola days >= days_left)
        threshold = next((t for t in THRESHOLDS if days_left <= t["days"]), None)
        if not threshold:
            continue

        # Dedup: c'è già una notifica recente con questo job_id+threshold_days?
        existing = (
            db.query(Notification)
            .filter(
                Notification.kind == "job_deadline_approaching",
                Notification.created_at >= cutoff_dt,
            )
            .all()
        )
        already = any(
            (n.payload or {}).get("job_id") == job.id
            and (n.payload or {}).get("threshold_days") == threshold["days"]
            for n in existing
        )
        if already:
            continue

        title = f"⏰ Deadline {threshold['label']} — {job.code}"
        body = f"Il job «{job.title}» scade il {job.end_date.strftime('%d/%m/%Y')}."
        notif_svc.notify_permission(
            db,
            permission="assign_resources",
            kind="job_deadline_approaching",
            severity=threshold["severity"],
            title=title,
            body=body,
            link=f"/jobs/{job.id}",
            payload={
                "job_id": job.id,
                "job_code": job.code,
                "end_date": job.end_date.isoformat(),
                "days_left": days_left,
                "threshold_days": threshold["days"],
            },
            tenant_id=tenant_id,
        )
        emitted += 1

    return emitted
