"""Seed di test per la notifica `job_deadline_approaching` (v3.4.28).

Crea (o aggiorna) un job con `end_date = oggi + 2 giorni` così che il
check al boot emetta una notifica `job_deadline_approaching` ai manager.

Idempotente: se cliente/progetto/job di test esistono già, li riusa.

Uso: python scripts/seed_test_deadline.py [DAYS_AHEAD]
  DAYS_AHEAD: giorni da oggi alla scadenza (default 2)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from datetime import date, timedelta

from app.database import SessionLocal
from app.models import Client, Job, JobStatus, Project, ProjectStatus

CLIENT_NAME = "TEST DEADLINE — Cliente fittizio"
PROJECT_CODE = "TEST-DEADLINE"
JOB_CODE = "JOB-TEST-DEADLINE"


def main() -> int:
    days_ahead = 2
    if len(sys.argv) > 1:
        try:
            days_ahead = max(1, int(sys.argv[1]))
        except ValueError:
            print(f"Argomento non valido '{sys.argv[1]}', uso default 2 giorni.")

    deadline = date.today() + timedelta(days=days_ahead)
    db = SessionLocal()
    try:
        # Cliente
        client = db.query(Client).filter(Client.name == CLIENT_NAME).first()
        if not client:
            client = Client(
                name=CLIENT_NAME,
                contact_email="test-deadline@mediaflow.it",
                tenant_id=1,
            )
            db.add(client); db.flush()
            print(f"  + Cliente creato: {client.name}")
        else:
            print(f"  · Cliente esistente: {client.name}")

        # Progetto
        project = db.query(Project).filter(Project.code == PROJECT_CODE).first()
        if not project:
            project = Project(
                code=PROJECT_CODE,
                title="Progetto Test Deadline",
                client_id=client.id,
                status=ProjectStatus.active,
                tenant_id=1,
            )
            db.add(project); db.flush()
            print(f"  + Progetto creato: {project.code}")
        else:
            print(f"  · Progetto esistente: {project.code}")

        # Job — aggiorna end_date se esiste, crea se manca
        job = db.query(Job).filter(Job.code == JOB_CODE).first()
        if not job:
            job = Job(
                code=JOB_CODE,
                title=f"Job Test Deadline (scadenza {deadline.strftime('%d/%m/%Y')})",
                project_id=project.id,
                client_id=client.id,
                status=JobStatus.active,
                start_date=date.today() - timedelta(days=5),
                end_date=deadline,
                budget_quoted=1000.0,
            )
            db.add(job)
            print(f"  + Job creato: {job.code} con scadenza {deadline.strftime('%d/%m/%Y')}")
        else:
            job.end_date = deadline
            job.status = JobStatus.active
            print(f"  · Job esistente aggiornato: {job.code} scadenza → {deadline.strftime('%d/%m/%Y')}")

        db.commit()
        print()
        print(f"✓ Seed completato. Job '{JOB_CODE}' scade il {deadline.strftime('%d/%m/%Y')} ({days_ahead} giorni da oggi).")
        print(f"  Per emettere la notifica subito: riavvia il server (check al boot)")
        print(f"  oppure POST /admin/api/check-deadlines (admin).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
