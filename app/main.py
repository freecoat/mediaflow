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
    tech_sheets, team, admin_data, help as help_router,
    billing,
    planning_diag, planning_unavailabilities,
    delivery_templates,
    suppliers as suppliers_router,
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
        # v3.5.0-alpha.70.4 — MFA TOTP
        mfa_alter = [
            ("mfa_secret_encrypted", "TEXT NULL"),
            ("mfa_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("mfa_enabled_at", "DATETIME NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in mfa_alter:
                if col not in cols:
                    print(f"[auto-migrate] users.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
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
        # v3.5.0-alpha.66.15.0 — sprint R1: tenant_id per scope multi-tenant
        quote_alter = [
            ("parent_quote_id", "INTEGER NULL REFERENCES quotes(id)"),
            ("superseded_by_id", "INTEGER NULL REFERENCES quotes(id)"),
            # v3.4.52 — phantom quote (reverse-flow)
            ("is_phantom", "BOOLEAN NOT NULL DEFAULT 0"),
            # v3.5.0-alpha.66.15.0 — tenant scope (R1)
            ("tenant_id", "INTEGER NOT NULL DEFAULT 1"),
        ]
        with engine.begin() as conn:
            for col, ddl in quote_alter:
                if col not in qcols:
                    print(f"[auto-migrate] quotes.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE quotes ADD COLUMN {col} {ddl}"))
    # v3.4.50.1 — QuoteLine: parent_line_id per eredità righe in versioning
    # v3.5.0-alpha.27 — QuoteLine: is_optional + section_label
    # v3.5.0-alpha.64 — QuoteLine: referred_from_jcl_id (link a JCL d'origine
    # per righe [EXTRA] generate da refer-to-sales)
    if "quote_lines" in insp.get_table_names():
        qlcols = {c["name"] for c in insp.get_columns("quote_lines")}
        ql_alter = [
            ("parent_line_id", "INTEGER NULL REFERENCES quote_lines(id)"),
            ("is_optional", "BOOLEAN NOT NULL DEFAULT 0"),
            ("section_label", "VARCHAR(120) NULL"),
            ("referred_from_jcl_id", "INTEGER NULL REFERENCES job_cost_lines(id)"),
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
    # v3.5.0-alpha.28 — ClientWork: campi estesi (synopsis, release_date,
    # funding_public, cast_crew, external_links, awards)
    if "client_works" in insp.get_table_names():
        cwcols = {c["name"] for c in insp.get_columns("client_works")}
        cw_alter = [
            ("synopsis", "TEXT NULL"),
            ("release_date", "DATE NULL"),
            ("funding_public", "TEXT NULL"),
            ("cast_crew", "TEXT NULL"),
            ("external_links", "TEXT NULL"),
            ("awards", "TEXT NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in cw_alter:
                if col not in cwcols:
                    print(f"[auto-migrate] client_works.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE client_works ADD COLUMN {col} {ddl}"))
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
    # v3.5.0-alpha.46 — Cost report → Billing flow: estensione JobCostLine
    # con stato fatturazione (billing_status, billing_batch_id, billed_amount).
    # Le NUOVE tabelle billing_batches, billing_batch_lines, loss_entries vengono
    # create automaticamente da Base.metadata.create_all() prima di questo step.
    if "job_cost_lines" in insp.get_table_names():
        jclcols = {c["name"] for c in insp.get_columns("job_cost_lines")}
        jcl_alter = [
            ("billing_status",   "VARCHAR(16) NOT NULL DEFAULT 'not_billed'"),
            ("billing_batch_id", "INTEGER NULL REFERENCES billing_batches(id)"),
            ("billed_amount",    "REAL NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in jcl_alter:
                if col not in jclcols:
                    print(f"[auto-migrate] job_cost_lines.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE job_cost_lines ADD COLUMN {col} {ddl}"))
    # v3.5.0-alpha.52 — Fattura PDF formale: dati fiscali estesi su tenant,
    # client, invoice (con snapshot al momento emissione), invoice_line.
    if "tenants" in insp.get_table_names():
        tcols = {c["name"] for c in insp.get_columns("tenants")}
        t_alter = [
            ("tax_code",                "VARCHAR(50) NULL"),
            ("iban",                    "VARCHAR(40) NULL"),
            ("sdi_code",                "VARCHAR(20) NULL"),
            ("rea_number",              "VARCHAR(40) NULL"),
            ("fiscal_capital",          "VARCHAR(80) NULL"),
            ("fiscal_regime",           "VARCHAR(8) NOT NULL DEFAULT 'RF01'"),
            ("payment_terms_default",   "INTEGER NOT NULL DEFAULT 30"),
            ("payment_method_default",  "VARCHAR(80) NOT NULL DEFAULT 'Bonifico bancario'"),
            ("invoice_footer",          "TEXT NULL"),
            # v3.5.0-alpha.66.13 — Branding aziendale
            ("tagline",                 "VARCHAR(255) NULL"),
            ("brand_color",             "VARCHAR(7) NULL"),
            ("show_powered_by",         "BOOLEAN NOT NULL DEFAULT 1"),
            ("document_header",         "TEXT NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in t_alter:
                if col not in tcols:
                    print(f"[auto-migrate] tenants.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE tenants ADD COLUMN {col} {ddl}"))
    if "clients" in insp.get_table_names():
        ccols = {c["name"] for c in insp.get_columns("clients")}
        c_alter = [
            ("zip_code", "VARCHAR(20) NULL"),
            ("province", "VARCHAR(4) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in c_alter:
                if col not in ccols:
                    print(f"[auto-migrate] clients.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE clients ADD COLUMN {col} {ddl}"))
    if "invoices" in insp.get_table_names():
        icols = {c["name"] for c in insp.get_columns("invoices")}
        i_alter = [
            ("doc_type",                    "VARCHAR(8) NOT NULL DEFAULT 'TD01'"),
            ("payment_method",              "VARCHAR(80) NULL"),
            ("payment_terms_days",          "INTEGER NULL"),
            ("iban_snapshot",               "VARCHAR(40) NULL"),
            ("client_legal_name_snap",      "VARCHAR(255) NULL"),
            ("client_vat_snap",             "VARCHAR(50) NULL"),
            ("client_tax_code_snap",        "VARCHAR(50) NULL"),
            ("client_pec_snap",             "VARCHAR(255) NULL"),
            ("client_sdi_snap",             "VARCHAR(20) NULL"),
            ("client_address_snap",         "TEXT NULL"),
            ("client_zip_snap",             "VARCHAR(20) NULL"),
            ("client_city_snap",            "VARCHAR(100) NULL"),
            ("client_province_snap",        "VARCHAR(4) NULL"),
            ("client_country_snap",         "VARCHAR(100) NULL"),
            ("tenant_legal_name_snap",      "VARCHAR(255) NULL"),
            ("tenant_vat_snap",             "VARCHAR(50) NULL"),
            ("tenant_tax_code_snap",        "VARCHAR(50) NULL"),
            ("tenant_address_snap",         "TEXT NULL"),
            ("tenant_email_snap",           "VARCHAR(255) NULL"),
            ("tenant_phone_snap",           "VARCHAR(50) NULL"),
            ("tenant_iban_snap",            "VARCHAR(40) NULL"),
            ("tenant_sdi_snap",             "VARCHAR(20) NULL"),
            ("tenant_rea_snap",             "VARCHAR(40) NULL"),
            ("tenant_fiscal_capital_snap",  "VARCHAR(80) NULL"),
            ("tenant_fiscal_regime_snap",   "VARCHAR(8) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in i_alter:
                if col not in icols:
                    print(f"[auto-migrate] invoices.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE invoices ADD COLUMN {col} {ddl}"))
    if "invoice_lines" in insp.get_table_names():
        ilcols = {c["name"] for c in insp.get_columns("invoice_lines")}
        il_alter = [
            ("vat_rate",     "REAL NOT NULL DEFAULT 22.0"),
            ("discount_pct", "REAL NOT NULL DEFAULT 0.0"),
        ]
        with engine.begin() as conn:
            for col, ddl in il_alter:
                if col not in ilcols:
                    print(f"[auto-migrate] invoice_lines.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE invoice_lines ADD COLUMN {col} {ddl}"))
    # v3.5.0-alpha.66.21 — α.67 cost-side: JobCostLine.total_cost_accrued.
    if "job_cost_lines" in insp.get_table_names():
        jclcols = {c["name"] for c in insp.get_columns("job_cost_lines")}
        if "total_cost_accrued" not in jclcols:
            print("[auto-migrate] job_cost_lines.total_cost_accrued mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE job_cost_lines ADD COLUMN total_cost_accrued "
                    "REAL NOT NULL DEFAULT 0"
                ))
    # v3.5.0-alpha.66.20 — Pagamenti fattura (cashflow revenue-side).
    # Tabella invoice_payments creata automaticamente da create_all() su DB nuovi;
    # qui solo l'ALTER per la colonna denormalizzata sulla tabella esistente.
    if "invoices" in insp.get_table_names():
        icols = {c["name"] for c in insp.get_columns("invoices")}
        if "amount_paid" not in icols:
            print("[auto-migrate] invoices.amount_paid mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE invoices ADD COLUMN amount_paid "
                    "REAL NOT NULL DEFAULT 0"
                ))
    # v3.5.0-alpha.69.1 — Backfill InvoicePayment per fatture legacy pagate
    # senza riga di pagamento. Senza questo backfill, /finance/cashflow
    # mostra 0 incassato per fatture marcate paid pre-α.66.20 (rotture
    # silenziose di /finance/cashflow su DB pre-storici).
    # Idempotente: skip se già processato (presenza payment con reference
    # 'BACKFILL_AUTOMIGRATE' indica run precedente).
    if "invoice_payments" in insp.get_table_names() and "invoices" in insp.get_table_names():
        with engine.begin() as conn:
            # Invoices non ha tenant_id (modello single-tenant per ora), uso default 1.
            backfill_rows = conn.execute(text("""
                SELECT i.id, i.total, i.issue_date
                FROM invoices i
                WHERE i.status = 'paid'
                  AND i.amount_paid = 0
                  AND NOT EXISTS (
                    SELECT 1 FROM invoice_payments p WHERE p.invoice_id = i.id
                  )
            """)).all()
            for inv_id, total, issue_date in backfill_rows:
                if not total or total <= 0:
                    continue
                conn.execute(text("""
                    INSERT INTO invoice_payments
                    (tenant_id, invoice_id, amount, payment_date, method, notes,
                     reference, recorded_by_user_id, created_at)
                    VALUES
                    (1, :iid, :amt, :pdate, NULL,
                     'Backfill auto-migrate v3.5.0-alpha.69.1 (legacy paid invoice)',
                     'BACKFILL_AUTOMIGRATE', NULL, datetime('now'))
                """), {
                    "iid": inv_id,
                    "amt": total,
                    "pdate": issue_date,
                })
                conn.execute(text(
                    "UPDATE invoices SET amount_paid = :amt WHERE id = :iid"
                ), {"amt": total, "iid": inv_id})
            if backfill_rows:
                print(f"[auto-migrate] backfill InvoicePayment per {len(backfill_rows)} "
                      f"fatture legacy paid (cashflow ora le conteggia)")
    # v3.5.0-alpha.77 — Quote forecast fields
    if "quotes" in insp.get_table_names():
        qcols = {c["name"] for c in insp.get_columns("quotes")}
        q_alter = [
            ("win_probability_pct", "REAL NULL"),
            ("expected_close_date", "DATE NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in q_alter:
                if col not in qcols:
                    print(f"[auto-migrate] quotes.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE quotes ADD COLUMN {col} {ddl}"))
    # v3.5.0-alpha.73 — AssetMovement extension digital + ingest_batch
    # SQLite NOT NULL su physical_asset_id (era required in α.72.0) → richiede
    # table rebuild se DB esistente con righe. Approccio: skip rebuild se 0
    # righe (DB nuovo), altrimenti 12-step manual migration. Per ora rebuild
    # solo se 0 righe (workflow attuale Matteo).
    if "asset_movements" in insp.get_table_names():
        amcols = {c["name"]: c for c in insp.get_columns("asset_movements")}
        needs_rebuild = (
            amcols.get("physical_asset_id", {}).get("nullable") is False
            and ("asset_id" not in amcols or "ingest_batch_id" not in amcols)
        )
        with engine.begin() as conn:
            row_count = conn.execute(text("SELECT COUNT(*) FROM asset_movements")).scalar() or 0
            if needs_rebuild:
                if row_count == 0:
                    print("[auto-migrate] asset_movements rebuild (0 rows): DROP+CREATE")
                    conn.execute(text("DROP TABLE asset_movements"))
                    # create_tables() più sotto ricrea con nuovo schema
                else:
                    print(f"[auto-migrate] asset_movements: {row_count} rows, "
                          "rebuild manuale necessario (vedi script futuro)")
                    # Fallback: aggiungi colonne nullable, lascia constraint
                    am_alter = [
                        ("asset_id", "INTEGER NULL REFERENCES assets(id)"),
                        ("ingest_batch_id", "INTEGER NULL REFERENCES ingest_batches(id)"),
                    ]
                    for col, ddl in am_alter:
                        if col not in amcols:
                            print(f"[auto-migrate] asset_movements.{col} ALTER (preserve)")
                            conn.execute(text(f"ALTER TABLE asset_movements ADD COLUMN {col} {ddl}"))
    # v3.5.0-alpha.72.1 — Tenant asset_numbering_config
    if "tenants" in insp.get_table_names():
        tcols = {c["name"] for c in insp.get_columns("tenants")}
        if "asset_numbering_config" not in tcols:
            print("[auto-migrate] tenants.asset_numbering_config mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE tenants ADD COLUMN asset_numbering_config TEXT NULL"
                ))
    # v3.5.0-alpha.72 — PhysicalAsset ownership + QR
    if "physical_assets" in insp.get_table_names():
        pacols = {c["name"] for c in insp.get_columns("physical_assets")}
        pa_alter = [
            ("owner_type", "VARCHAR(20) NOT NULL DEFAULT 'internal'"),
            ("owner_client_id", "INTEGER NULL REFERENCES clients(id)"),
            ("owner_supplier_id", "INTEGER NULL REFERENCES suppliers(id)"),
            ("owner_label", "VARCHAR(255) NULL"),
            ("qr_code_token", "VARCHAR(64) NULL"),
            ("logistics_status", "VARCHAR(40) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in pa_alter:
                if col not in pacols:
                    print(f"[auto-migrate] physical_assets.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE physical_assets ADD COLUMN {col} {ddl}"))
            # Populate qr_code_token per asset esistenti senza token
            import uuid as _uuid
            rows = conn.execute(text(
                "SELECT id FROM physical_assets WHERE qr_code_token IS NULL"
            )).all()
            for (aid,) in rows:
                conn.execute(text(
                    "UPDATE physical_assets SET qr_code_token = :tk WHERE id = :id"
                ), {"tk": _uuid.uuid4().hex, "id": aid})
            if rows:
                print(f"[auto-migrate] populated qr_code_token su {len(rows)} physical_assets")
    # v3.5.0-alpha.70.3 — TPN security policy fields su projects.
    if "projects" in insp.get_table_names():
        pcols = {c["name"] for c in insp.get_columns("projects")}
        proj_alter = [
            ("ip_allowlist", "TEXT NULL"),
            ("mfa_required", "BOOLEAN NOT NULL DEFAULT 0"),
            ("min_role_for_access", "VARCHAR(40) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in proj_alter:
                if col not in pcols:
                    print(f"[auto-migrate] projects.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col} {ddl}"))
    # v3.5.0-alpha.65 — Pass-through OT al cliente (opt-in per progetto).
    if "jobs" in insp.get_table_names():
        jcols = {c["name"] for c in insp.get_columns("jobs")}
        if "weighted_revenue" not in jcols:
            print("[auto-migrate] jobs.weighted_revenue mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE jobs ADD COLUMN weighted_revenue "
                    "BOOLEAN NOT NULL DEFAULT 0"
                ))
    # v3.5.0-alpha.66.9 — JobDeliverable + cost-rate Resource + DAM physical.
    # Le NUOVE tabelle job_deliverables e physical_assets vengono create
    # automaticamente da Base.metadata.create_all() prima di questa funzione.
    # Qui solo le ALTER TABLE per le colonne aggiunte a tabelle esistenti.
    if "bookings" in insp.get_table_names():
        bcols = {c["name"] for c in insp.get_columns("bookings")}
        if "job_deliverable_id" not in bcols:
            print("[auto-migrate] bookings.job_deliverable_id mancante -> ALTER TABLE")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE bookings ADD COLUMN job_deliverable_id INTEGER NULL "
                    "REFERENCES job_deliverables(id)"
                ))
    if "assets" in insp.get_table_names():
        acols = {c["name"] for c in insp.get_columns("assets")}
        asset_alter = [
            ("job_deliverable_id",     "INTEGER NULL REFERENCES job_deliverables(id)"),
            ("is_internal_archive",    "BOOLEAN NOT NULL DEFAULT 0"),
            ("is_delivered_external",  "BOOLEAN NOT NULL DEFAULT 0"),
            ("delivered_at",           "DATETIME NULL"),
            ("delivered_to",           "VARCHAR(255) NULL"),
            ("delivery_method",        "VARCHAR(80) NULL"),
            ("delivery_tracking",      "VARCHAR(255) NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in asset_alter:
                if col not in acols:
                    print(f"[auto-migrate] assets.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE assets ADD COLUMN {col} {ddl}"))
    if "resources" in insp.get_table_names():
        rcols = {c["name"] for c in insp.get_columns("resources")}
        resource_alter = [
            ("cost_type",                "VARCHAR(20) NULL"),
            ("monthly_gross_salary",     "REAL NULL"),
            ("annual_bonus_months",      "REAL NULL"),
            ("cost_multiplier_oneri",    "REAL NULL"),
            ("annual_working_hours",     "REAL NULL"),
            ("freelance_hourly_cost",    "REAL NULL"),
            ("studio_hourly_cost",       "REAL NULL"),
        ]
        with engine.begin() as conn:
            for col, ddl in resource_alter:
                if col not in rcols:
                    print(f"[auto-migrate] resources.{col} mancante -> ALTER TABLE")
                    conn.execute(text(f"ALTER TABLE resources ADD COLUMN {col} {ddl}"))

    # v3.5.0-alpha.66.5 — Stato unificato booking (BookingState canonico).
    # Aggiunge bookings.state e popola dai legacy (status + execution_status).
    if "bookings" in insp.get_table_names():
        bcols = {c["name"] for c in insp.get_columns("bookings")}
        if "state" not in bcols:
            print("[auto-migrate] bookings.state mancante -> ALTER TABLE + populate")
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE bookings ADD COLUMN state VARCHAR(20) "
                    "NOT NULL DEFAULT 'tentative'"
                ))
                # Popola: cancelled → cancelled; tentative → tentative;
                # confirmed + execution → in_progress/done/not_done o confirmed
                conn.execute(text("""
                    UPDATE bookings
                    SET state = CASE
                        WHEN status = 'cancelled' THEN 'cancelled'
                        WHEN status = 'tentative' THEN 'tentative'
                        WHEN execution_status = 'in_progress' THEN 'in_progress'
                        WHEN execution_status = 'done' THEN 'done'
                        WHEN execution_status = 'not_done' THEN 'not_done'
                        ELSE 'confirmed'
                    END
                """))

    # v3.5.0-alpha.66.15.0 — Sprint R1: tenant scope per modelli orfani.
    # Audit HIGH #1: Quote/Job/JobCostLine/Asset non avevano tenant_id.
    # Aggiunto come INTEGER NOT NULL DEFAULT 1 → backfill automatico per i
    # record esistenti. Multi-tenant hard sarà attivato in Fase 7 quando
    # tenant_id sarà popolato durante il login. Project già ce l'ha.
    for tbl in ("jobs", "job_cost_lines", "assets"):
        if tbl in insp.get_table_names():
            tcols = {c["name"] for c in insp.get_columns(tbl)}
            if "tenant_id" not in tcols:
                print(f"[auto-migrate] {tbl}.tenant_id mancante -> ALTER TABLE (R1)")
                with engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE {tbl} ADD COLUMN tenant_id INTEGER NOT NULL DEFAULT 1"
                    ))


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
    # v3.5.0-alpha.66.7 — Bootstrap preset listino built-in. I file in
    # app/data/pricelist_presets/*.json vengono caricati come
    # PricelistSnapshot kind=preset al boot, una volta per tenant.
    # Idempotente: se già esiste uno snapshot preset con stesso nome
    # derivato dal filename, viene saltato. I preset NON vengono mai
    # applicati automaticamente al listino — sono solo "pronti all'uso"
    # nella UI di /pricelist → 📦 Snapshot → Preset.
    try:
        from app.database import SessionLocal
        from app.models import (
            PricelistSnapshot, PricelistSnapshotKind, Tenant,
        )
        from app.services import pricelist_snapshot as _plsnap
        _db = SessionLocal()
        try:
            tenants = _db.query(Tenant).all()
            preset_files = _plsnap.list_preset_files()
            loaded = 0
            for tenant in tenants:
                for preset_path in preset_files:
                    preset_name = f"Preset: {preset_path.stem}"
                    existing = (
                        _db.query(PricelistSnapshot)
                        .filter(
                            PricelistSnapshot.tenant_id == tenant.id,
                            PricelistSnapshot.kind == PricelistSnapshotKind.preset,
                            PricelistSnapshot.name == preset_name,
                            PricelistSnapshot.deleted_at.is_(None),
                        )
                        .first()
                    )
                    if existing:
                        continue
                    try:
                        payload = _plsnap.load_preset_payload(preset_path.name)
                        _plsnap.create_snapshot_record(
                            _db,
                            tenant_id=tenant.id,
                            name=preset_name,
                            description=payload.get("description") or f"Preset {preset_path.name}",
                            kind=PricelistSnapshotKind.preset,
                            user_id=None,
                            payload=payload,
                        )
                        loaded += 1
                    except Exception as inner_e:
                        print(f"[lifespan] preset {preset_path.name} skipped: {inner_e}")
            if loaded:
                _db.commit()
                print(f"[lifespan] pricelist presets bootstrapped: {loaded}")
        finally:
            _db.close()
    except Exception as e:
        print(f"[lifespan] bootstrap pricelist presets failed: {e}")
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
    # v3.5.0-alpha.51 — Cleanup attachments copilot vecchi (> 7gg)
    try:
        from app.services.copilot_attachments import cleanup_old_attachments
        n = cleanup_old_attachments()
        if n:
            print(f"[lifespan] cleanup_old_attachments: {n} file copilot eliminati")
    except Exception as e:
        print(f"[lifespan] cleanup_old_attachments failed: {e}")
    # v3.5.0-alpha.51.1 fix C1 — Backfill JobCostLine.work_date dai booking
    # done. Le JCL pre-α.51.1 hanno work_date NULL, quindi billing.preview
    # cade nel fallback "current_month". Eseguito una volta sola: marker file
    # uploads/.work_date_backfilled per evitare re-run a ogni boot.
    try:
        marker = Path("uploads") / ".work_date_backfilled_v1"
        if not marker.exists():
            from app.database import SessionLocal
            from app.models import JobCostLine
            from app.services.cost_line_sync import recompute_cost_line_actual
            _db = SessionLocal()
            try:
                jcls = _db.query(JobCostLine).filter(JobCostLine.work_date.is_(None)).all()
                touched = 0
                for jcl in jcls:
                    r = recompute_cost_line_actual(_db, jcl)
                    if r.get("updated"):
                        touched += 1
                _db.commit()
                marker.write_text("ok")
                if touched:
                    print(f"[lifespan] backfill JCL.work_date: {touched}/{len(jcls)} righe popolate")
            finally:
                _db.close()
    except Exception as e:
        print(f"[lifespan] backfill JCL.work_date failed: {e}")
    # v3.5.0-alpha.55 — Backfill JobCostLine.total_expected dai booking.
    # Pre-α.55 total_expected era riempito solo da edit manuale, quindi
    # in molti DB esistenti vale = total_quoted e Over/Under viene 0.
    # Eseguito una volta sola: marker file uploads/.total_expected_backfilled_v1.
    try:
        marker = Path("uploads") / ".total_expected_backfilled_v1"
        if not marker.exists():
            from app.database import SessionLocal
            from app.models import JobCostLine
            from app.services.cost_line_sync import recompute_cost_line_actual
            _db = SessionLocal()
            try:
                jcls = _db.query(JobCostLine).all()
                touched = 0
                for jcl in jcls:
                    r = recompute_cost_line_actual(_db, jcl)
                    if r.get("updated"):
                        touched += 1
                _db.commit()
                marker.write_text("ok")
                if touched:
                    print(f"[lifespan] backfill JCL.total_expected: {touched}/{len(jcls)} righe ricalcolate")
            finally:
                _db.close()
    except Exception as e:
        print(f"[lifespan] backfill JCL.total_expected failed: {e}")
    # v3.5.0-alpha.58 — Backfill JCLBilledSlice da BillingBatch già fatturati.
    # Foundation per α.59 (hard-block backedit booking dentro periodo slice-ato)
    # e α.60 (cost report 3 colonne). Per ogni BillingBatchLine appartenente a
    # un batch invoiced con total_approved > 0 si crea uno slice retroattivo
    # con periodo del batch e snapshot quantità/importo della line.
    # Eseguito una volta sola: marker file uploads/.billed_slices_backfilled_v1.
    try:
        marker = Path("uploads") / ".billed_slices_backfilled_v1"
        if not marker.exists():
            from app.database import SessionLocal
            from app.models import (
                BillingBatch, BillingBatchLine, BillingBatchStatus,
                JCLBilledSlice,
            )
            _db = SessionLocal()
            try:
                batches = _db.query(BillingBatch).filter(
                    BillingBatch.status == BillingBatchStatus.invoiced
                ).all()
                created = 0
                skipped = 0
                for batch in batches:
                    for line in batch.lines:
                        if (line.total_approved or 0) <= 0.001:
                            continue
                        existing = _db.query(JCLBilledSlice).filter(
                            JCLBilledSlice.billing_batch_line_id == line.id
                        ).first()
                        if existing:
                            skipped += 1
                            continue
                        slice_ = JCLBilledSlice(
                            tenant_id=batch.tenant_id or 1,
                            job_cost_line_id=line.job_cost_line_id,
                            billing_batch_line_id=line.id,
                            invoice_id=batch.invoice_id,
                            period_start=batch.period_start,
                            period_end=batch.period_end,
                            billed_quantity=line.quantity or 0.0,
                            billed_amount=line.total_approved or 0.0,
                            unit_price_snap=line.unit_price or 0.0,
                        )
                        _db.add(slice_)
                        created += 1
                _db.commit()
                marker.write_text("ok")
                if created or skipped:
                    print(
                        f"[lifespan] backfill JCLBilledSlice: "
                        f"{created} creati, {skipped} già presenti, "
                        f"{len(batches)} batch invoiced scansionati"
                    )
            finally:
                _db.close()
    except Exception as e:
        print(f"[lifespan] backfill JCLBilledSlice failed: {e}")
    yield


app = FastAPI(title="MediaFlow", version="3.5.0-alpha.86", lifespan=lifespan)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
# v3.5.0-alpha.51 — Mount /uploads per servire allegati copilot (immagini
# caricate vengono linkate via URL pubblico). Cleanup auto > 7 giorni
# (vedi copilot_attachments.cleanup_old_attachments).
_uploads_dir = Path("uploads")
_uploads_dir.mkdir(exist_ok=True)
(_uploads_dir / "copilot").mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_uploads_dir), name="uploads")
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
# v3.5.0-alpha.51.1: /uploads/ NON più public — il mount StaticFiles era
# auth-bypass su DAM e capitolati copilot. Il browser di un utente loggato
# manda automaticamente il cookie access_token, quindi gli URL /uploads/*
# inline nei template continuano a funzionare. Senza login → redirect /auth.
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
app.include_router(planning_diag.router)
app.include_router(planning_unavailabilities.router)
app.include_router(delivery_templates.router)
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
app.include_router(admin_data.router)
from app.routers import physical_assets as physical_assets_router
app.include_router(physical_assets_router.router)
app.include_router(help_router.router)
app.include_router(suppliers_router.router)
app.include_router(billing.router)


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
