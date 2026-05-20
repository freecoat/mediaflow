"""
MediaFlow — project_purge (v3.5.0-alpha.172.2)

Hard-delete cascade di un Project: rimuove TUTTO l'albero (Quote, Job,
JCL, Booking, Invoice, Asset, ...) in ordine FK-safe + singola transazione.

Pensato per workflow ADMIN-ONLY di test/cleanup. Non per produzione
standard (la prassi è soft-delete sul progetto).

Spec di riferimento: docs/RESTRUCTURE_2026_05_20.md sezione 6.

Uso programmatico:
  from app.services.project_purge import hard_delete_project
  report = hard_delete_project(db, project_id=X, actor_user_id=Y)

Errori:
  - ValueError se project_id non esiste
  - PermissionError ATTESO che il caller verifichi RBAC admin prima
    della chiamata (non lo facciamo qui per riusabilità).

Output: dict counters per ogni tabella + project_code.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def hard_delete_project(
    db: Session,
    project_id: int,
    actor_user_id: Optional[int] = None,
) -> dict:
    """Hard-delete cascade FK-safe in singola transazione.
    Restituisce counter rows cancellate per tabella + project_code per log.

    Rollback automatico SQLAlchemy su exception (caller usa db.begin()).
    """
    from app.models import Project

    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise ValueError(f"Project {project_id} non trovato")

    project_code = proj.code
    counters: dict[str, int] = {}

    log.warning(
        f"[project_purge] HARD-DELETE project #{project_id} '{project_code}' "
        f"requested by user_id={actor_user_id}"
    )

    # Helper introspettivo: skippa step se colonna o tabella mancante.
    def _has_column(table: str, col: str) -> bool:
        try:
            rows = db.execute(text(f"PRAGMA table_info({table})")).all()
            return any(r[1] == col for r in rows)
        except Exception:
            return False

    def _run(table: str, sql: str, **bind):
        try:
            res = db.execute(text(sql).bindparams(**bind))
            counters[table] = counters.get(table, 0) + (res.rowcount or 0)
        except Exception as e:
            log.error(f"[project_purge] FAILED on {table}: {e}")
            raise

    def _run_safe(table: str, col_check: tuple, sql: str, **bind):
        """Esegue solo se tutte le colonne in col_check (lista di (table, col))
        esistono. Skip silente altrimenti."""
        for tbl, col in col_check:
            if not _has_column(tbl, col):
                log.info(f"[project_purge] skip {table}: missing {tbl}.{col}")
                counters[table] = counters.get(table, 0)
                return
        _run(table, sql, **bind)

    pid = project_id

    # 1. AI subtree
    _run("ai_messages", """
        DELETE FROM ai_messages WHERE conversation_id IN (
            SELECT id FROM ai_conversations WHERE project_id = :pid
        )
    """, pid=pid)
    # AI actions: link via conversation_id (non ha project_id diretto)
    _run("ai_actions", """
        DELETE FROM ai_actions WHERE conversation_id IN (
            SELECT id FROM ai_conversations WHERE project_id = :pid
        )
    """, pid=pid)
    _run("ai_conversations", "DELETE FROM ai_conversations WHERE project_id = :pid", pid=pid)

    # 2. Notifications con project_id (colonna opzionale)
    _run_safe("notifications", [("notifications", "project_id")],
              "DELETE FROM notifications WHERE project_id = :pid", pid=pid)

    # 3. Anomaly entries
    _run_safe("anomaly_entries", [("anomaly_entries", "project_id")],
              "DELETE FROM anomaly_entries WHERE project_id = :pid", pid=pid)

    # 4. Project access grants + tech sheets + milestones
    _run_safe("project_access_grants", [("project_access_grants", "project_id")],
              "DELETE FROM project_access_grants WHERE project_id = :pid", pid=pid)
    _run_safe("project_tech_sheets", [("project_tech_sheets", "project_id")],
              "DELETE FROM project_tech_sheets WHERE project_id = :pid", pid=pid)
    _run_safe("project_milestones", [("project_milestones", "project_id")],
              "DELETE FROM project_milestones WHERE project_id = :pid", pid=pid)

    # 5. Booking subtree
    _run("booking_changes", """
        DELETE FROM booking_changes WHERE booking_id IN (
            SELECT b.id FROM bookings b
            LEFT JOIN jobs j ON j.id = b.job_id
            WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("booking_deliverables", """
        DELETE FROM booking_deliverables WHERE booking_id IN (
            SELECT b.id FROM bookings b
            JOIN jobs j ON j.id = b.job_id
            WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("booking_assignments", """
        DELETE FROM booking_assignments WHERE booking_id IN (
            SELECT b.id FROM bookings b
            JOIN jobs j ON j.id = b.job_id
            WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("bookings", """
        DELETE FROM bookings WHERE job_id IN (
            SELECT id FROM jobs WHERE project_id = :pid
        )
    """, pid=pid)

    # 6. Timesheets, time_punches, job_resource_assignments
    _run("timesheets", """
        DELETE FROM timesheets WHERE job_id IN (
            SELECT id FROM jobs WHERE project_id = :pid
        )
    """, pid=pid)
    _run("time_punches", """
        DELETE FROM time_punches WHERE job_id IN (
            SELECT id FROM jobs WHERE project_id = :pid
        )
    """, pid=pid)
    _run("job_resource_assignments", """
        DELETE FROM job_resource_assignments WHERE job_id IN (
            SELECT id FROM jobs WHERE project_id = :pid
        )
    """, pid=pid)

    # 7. Slices fatturazione + Advance allocations + consumptions
    _run("jcl_billed_slices", """
        DELETE FROM jcl_billed_slices WHERE job_cost_line_id IN (
            SELECT jcl.id FROM job_cost_lines jcl
            JOIN jobs j ON j.id = jcl.job_id WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("deliverable_billed_slices", """
        DELETE FROM deliverable_billed_slices WHERE job_deliverable_id IN (
            SELECT d.id FROM job_deliverables d
            JOIN jobs j ON j.id = d.job_id WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("advance_payment_consumptions", """
        DELETE FROM advance_payment_consumptions WHERE advance_payment_id IN (
            SELECT id FROM advance_payments WHERE project_id = :pid
        )
    """, pid=pid)
    _run("advance_payment_allocations", """
        DELETE FROM advance_payment_allocations WHERE advance_payment_id IN (
            SELECT id FROM advance_payments WHERE project_id = :pid
        )
    """, pid=pid)
    _run("advance_payment_deliverable_allocations", """
        DELETE FROM advance_payment_deliverable_allocations WHERE advance_payment_id IN (
            SELECT id FROM advance_payments WHERE project_id = :pid
        )
    """, pid=pid)
    _run("advance_payments", "DELETE FROM advance_payments WHERE project_id = :pid", pid=pid)

    # 8. Quote schedules/allocations
    _run("quote_advance_allocations", """
        DELETE FROM quote_advance_allocations WHERE schedule_id IN (
            SELECT s.id FROM quote_advance_schedules s
            JOIN quotes q ON q.id = s.quote_id WHERE q.project_id = :pid
        )
    """, pid=pid)
    _run("quote_advance_schedules", """
        DELETE FROM quote_advance_schedules WHERE quote_id IN (
            SELECT id FROM quotes WHERE project_id = :pid
        )
    """, pid=pid)

    # 9. Invoices + lines + payments + billing batches + loss_entries
    _run("invoice_lines", """
        DELETE FROM invoice_lines WHERE invoice_id IN (
            SELECT id FROM invoices WHERE project_id = :pid
                OR job_id IN (SELECT id FROM jobs WHERE project_id = :pid)
        )
    """, pid=pid)
    _run("invoice_payments", """
        DELETE FROM invoice_payments WHERE invoice_id IN (
            SELECT id FROM invoices WHERE project_id = :pid
                OR job_id IN (SELECT id FROM jobs WHERE project_id = :pid)
        )
    """, pid=pid)
    _run("billing_batch_lines", """
        DELETE FROM billing_batch_lines WHERE batch_id IN (
            SELECT id FROM billing_batches WHERE project_id = :pid
        )
    """, pid=pid)
    _run("billing_batches", """
        DELETE FROM billing_batches WHERE project_id = :pid
    """, pid=pid)
    _run("loss_entries", "DELETE FROM loss_entries WHERE project_id = :pid", pid=pid)
    _run("invoices", """
        DELETE FROM invoices WHERE project_id = :pid
            OR job_id IN (SELECT id FROM jobs WHERE project_id = :pid)
    """, pid=pid)

    # 10. VFXShots + DeliverableSpecs + DeliverableAssets + JobDeliverables
    _run("vfx_shots", """
        DELETE FROM vfx_shots WHERE job_deliverable_id IN (
            SELECT d.id FROM job_deliverables d
            JOIN jobs j ON j.id = d.job_id WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("deliverable_specs", """
        DELETE FROM deliverable_specs WHERE job_deliverable_id IN (
            SELECT d.id FROM job_deliverables d
            JOIN jobs j ON j.id = d.job_id WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("deliverable_assets", """
        DELETE FROM deliverable_assets WHERE job_deliverable_id IN (
            SELECT d.id FROM job_deliverables d
            JOIN jobs j ON j.id = d.job_id WHERE j.project_id = :pid
        )
    """, pid=pid)
    _run("job_deliverables", """
        DELETE FROM job_deliverables WHERE job_id IN (
            SELECT id FROM jobs WHERE project_id = :pid
        )
    """, pid=pid)

    # 11. JCL
    _run("job_cost_lines", """
        DELETE FROM job_cost_lines WHERE job_id IN (
            SELECT id FROM jobs WHERE project_id = :pid
        )
    """, pid=pid)

    # 12. Jobs
    _run("jobs", "DELETE FROM jobs WHERE project_id = :pid", pid=pid)

    # 13. Quote lines + Quotes
    _run("quote_lines", """
        DELETE FROM quote_lines WHERE quote_id IN (
            SELECT id FROM quotes WHERE project_id = :pid
        )
    """, pid=pid)
    _run("quotes", "DELETE FROM quotes WHERE project_id = :pid", pid=pid)

    # 14. Asset subtree
    _run("asset_access_logs", """
        DELETE FROM asset_access_logs WHERE asset_id IN (
            SELECT id FROM assets WHERE project_id = :pid
        )
    """, pid=pid)
    _run("asset_tags", """
        DELETE FROM asset_tags WHERE asset_id IN (
            SELECT id FROM assets WHERE project_id = :pid
        )
    """, pid=pid)
    _run("asset_movements", """
        DELETE FROM asset_movements WHERE physical_asset_id IN (
            SELECT id FROM physical_assets WHERE project_id = :pid
        )
    """, pid=pid)
    _run("asset_memberships", """
        DELETE FROM asset_memberships WHERE physical_asset_id IN (
            SELECT id FROM physical_assets WHERE project_id = :pid
        ) OR asset_id IN (
            SELECT id FROM assets WHERE project_id = :pid
        )
    """, pid=pid)
    _run("ingest_batches", "DELETE FROM ingest_batches WHERE project_id = :pid", pid=pid)
    _run("assets", "DELETE FROM assets WHERE project_id = :pid", pid=pid)
    _run("physical_assets", "DELETE FROM physical_assets WHERE project_id = :pid", pid=pid)

    # 15. Project finale
    _run("projects", "DELETE FROM projects WHERE id = :pid", pid=pid)

    log.warning(
        f"[project_purge] DONE project #{project_id} '{project_code}': "
        f"counters={counters}"
    )

    return {
        "project_id": project_id,
        "project_code": project_code,
        "actor_user_id": actor_user_id,
        "counters": counters,
    }
