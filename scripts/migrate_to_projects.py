"""
MediaFlow — migrazione schema v1 → v2

Aggiunge l'entità `Project` tra Client e Quote:
  - Prima: Client → Quote → Job
  - Dopo:  Client → Project → Quote → Job

Lo script è NON-DISTRUTTIVO:
  - Crea la tabella `projects` se non esiste
  - Aggiunge `project_id` a `quotes` e `jobs` se mancante
  - Per ogni Quote/Job esistente senza project_id, crea automaticamente
    un Project "legacy" basato sui dati della quotazione/job stesso

Esegui una sola volta dopo l'aggiornamento:
  python scripts/migrate_to_projects.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text
from app.database import SessionLocal, engine, create_tables
from app.models import Project, Client, Quote, Job, ProjectStatus


def column_exists(table: str, column: str) -> bool:
    insp = inspect(engine)
    return column in [c["name"] for c in insp.get_columns(table)]


def table_exists(table: str) -> bool:
    insp = inspect(engine)
    return table in insp.get_table_names()


def migrate():
    print("▸ MediaFlow · migrazione schema v1 → v2 (Projects)")
    print("─" * 60)

    create_tables()
    print("✓ create_all eseguito (tabelle nuove create se mancanti)")

    if not table_exists("projects"):
        print("✗ Errore: tabella projects non creata. Verifica i modelli.")
        return

    db = SessionLocal()
    try:
        insp = inspect(engine)

        quotes_cols = [c["name"] for c in insp.get_columns("quotes")]
        if "project_id" not in quotes_cols:
            print("▸ Aggiungo quotes.project_id (SQLite: ALTER TABLE ADD COLUMN)")
            db.execute(text("ALTER TABLE quotes ADD COLUMN project_id INTEGER"))
            db.commit()

        jobs_cols = [c["name"] for c in insp.get_columns("jobs")]
        if "project_id" not in jobs_cols:
            print("▸ Aggiungo jobs.project_id")
            db.execute(text("ALTER TABLE jobs ADD COLUMN project_id INTEGER"))
            db.commit()

        orphan_quotes = db.query(Quote).filter(Quote.project_id.is_(None)).all()
        orphan_jobs = db.query(Job).filter(Job.project_id.is_(None)).all()

        if not orphan_quotes and not orphan_jobs:
            print("✓ Nessun dato legacy da migrare")
            return

        print(f"▸ Trovate {len(orphan_quotes)} quote e {len(orphan_jobs)} job senza project_id")

        created_count = 0

        by_client_title: dict[tuple[int, str], Project] = {}

        for q in orphan_quotes:
            key = (q.client_id, q.title.strip() if q.title else f"legacy-quote-{q.id}")
            existing = db.query(Project).filter(
                Project.client_id == key[0],
                Project.title == key[1]
            ).first()

            if existing:
                by_client_title[key] = existing
            else:
                p_code = f"LEGACY-Q{q.id}"
                counter = 1
                while db.query(Project).filter(Project.code == p_code).first():
                    p_code = f"LEGACY-Q{q.id}-{counter}"
                    counter += 1

                project = Project(
                    code=p_code,
                    title=q.title or f"Progetto legacy {q.id}",
                    client_id=q.client_id,
                    length_minutes=q.length_minutes,
                    fps=q.fps,
                    delivery_format=q.delivery_format,
                    shooting_format=q.shooting_format,
                    status=ProjectStatus.active if q.status.value == "approved" else ProjectStatus.quoting,
                    description=f"Progetto creato automaticamente dalla migrazione dalla quotazione {q.number}",
                )
                db.add(project)
                db.flush()
                by_client_title[key] = project
                created_count += 1
                print(f"  ✓ Creato progetto '{project.code}' per quote {q.number}")

            q.project_id = by_client_title[key].id

        for j in orphan_jobs:
            if j.quote_id:
                linked_quote = db.query(Quote).filter(Quote.id == j.quote_id).first()
                if linked_quote and linked_quote.project_id:
                    j.project_id = linked_quote.project_id
                    continue

            p_code = f"LEGACY-J{j.id}"
            counter = 1
            while db.query(Project).filter(Project.code == p_code).first():
                p_code = f"LEGACY-J{j.id}-{counter}"
                counter += 1
            project = Project(
                code=p_code,
                title=j.title,
                client_id=j.client_id,
                status=ProjectStatus.active,
                description=f"Progetto creato automaticamente dalla migrazione dal job {j.code}",
            )
            db.add(project)
            db.flush()
            j.project_id = project.id
            created_count += 1
            print(f"  ✓ Creato progetto '{project.code}' per job {j.code}")

        db.commit()
        print("─" * 60)
        print(f"✓ Migrazione completata: {created_count} progetti legacy creati")
        print(f"  {len(orphan_quotes)} quote e {len(orphan_jobs)} job collegati")

    except Exception as e:
        db.rollback()
        print(f"✗ Errore durante migrazione: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
