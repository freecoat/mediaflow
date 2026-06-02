"""v3.5.0-alpha.172.174 — Cascade purge finance+deliverable su delete progetto.

Verifica che `_purge_project_dependents` cancelli invoices / advance_payments /
quote_advance_schedules / job_deliverables (+ figli) del progetto purgato, SENZA
toccare quelli di altri progetti (scoping). Root cause del "acconto fantasma" su GLO:
il purge non cascatava sul finance → orfani che inquinavano altri progetti.
"""
from sqlalchemy import text
from app.services.soft_delete import _purge_project_dependents

CREATED = "'2026-01-01 00:00:00'"


def _exec(db, sql):
    db.execute(text(sql))


def _seed(db):
    # ── TARGET (project 99, job 88, quote 77, jcl 66) ──
    _exec(db, f"INSERT INTO invoices (id,number,client_id,status,issue_date,subtotal,vat_rate,total,created_at,doc_type,amount_paid,is_closing,kind,tenant_id,currency,fx_rate_to_base,project_id,job_id) VALUES (901,'T-1',1,'draft','2026-01-01',100,22,122,{CREATED},'invoice',0,0,'advance',1,'EUR',1,99,NULL)")
    _exec(db, f"INSERT INTO invoices (id,number,client_id,status,issue_date,subtotal,vat_rate,total,created_at,doc_type,amount_paid,is_closing,kind,tenant_id,currency,fx_rate_to_base,project_id,job_id) VALUES (902,'T-2',1,'draft','2026-01-01',100,22,122,{CREATED},'invoice',0,0,'regular',1,'EUR',1,NULL,88)")
    _exec(db, "INSERT INTO invoice_lines (id,invoice_id,description,quantity,unit_price,total,vat_rate,discount_pct) VALUES (911,901,'x',1,100,100,22,0)")
    _exec(db, f"INSERT INTO advance_payments (id,tenant_id,project_id,amount,balance_remaining,status,created_at) VALUES (921,1,99,500,500,'draft',{CREATED})")
    _exec(db, "INSERT INTO advance_payment_allocations (id,advance_payment_id,job_cost_line_id,amount) VALUES (931,921,66,500)")
    _exec(db, f"INSERT INTO quote_advance_schedules (id,tenant_id,quote_id,label,due_anchor,due_offset_days,sort_order,created_at) VALUES (941,1,77,'L','quote_approved',0,0,{CREATED})")
    _exec(db, f"INSERT INTO job_deliverables (id,tenant_id,job_id,name,nature,status,created_at,updated_at,unit_price,unit_nature,quantity_planned,quantity_delivered,total_quoted,total_accrued,total_cost_accrued,accrued_stale,billing_status) VALUES (951,1,88,'D','digital','planned',{CREATED},{CREATED},0,'deliverable_qty',1,0,0,0,0,0,'not_billed')")

    # ── SURVIVOR (project 42, job 40, quote 41) — NON deve sparire ──
    _exec(db, f"INSERT INTO invoices (id,number,client_id,status,issue_date,subtotal,vat_rate,total,created_at,doc_type,amount_paid,is_closing,kind,tenant_id,currency,fx_rate_to_base,project_id,job_id) VALUES (990,'S-1',1,'draft','2026-01-01',100,22,122,{CREATED},'invoice',0,0,'advance',1,'EUR',1,42,NULL)")
    _exec(db, f"INSERT INTO advance_payments (id,tenant_id,project_id,amount,balance_remaining,status,created_at) VALUES (991,1,42,500,500,'draft',{CREATED})")
    _exec(db, f"INSERT INTO quote_advance_schedules (id,tenant_id,quote_id,label,due_anchor,due_offset_days,sort_order,created_at) VALUES (992,1,41,'L','quote_approved',0,0,{CREATED})")
    _exec(db, f"INSERT INTO job_deliverables (id,tenant_id,job_id,name,nature,status,created_at,updated_at,unit_price,unit_nature,quantity_planned,quantity_delivered,total_quoted,total_accrued,total_cost_accrued,accrued_stale,billing_status) VALUES (993,1,40,'D','digital','planned',{CREATED},{CREATED},0,'deliverable_qty',1,0,0,0,0,0,'not_billed')")
    db.flush()


def _count(db, sql):
    return db.execute(text(sql)).scalar()


def test_purge_cascade_removes_target_keeps_survivor(db):
    _seed(db)
    res = _purge_project_dependents(db, project_id=99, job_ids=[88], quote_ids=[77], jcl_ids=[66])

    # TARGET tutto sparito
    assert _count(db, "SELECT COUNT(*) FROM invoices WHERE id IN (901,902)") == 0
    assert _count(db, "SELECT COUNT(*) FROM invoice_lines WHERE id=911") == 0
    assert _count(db, "SELECT COUNT(*) FROM advance_payments WHERE id=921") == 0
    assert _count(db, "SELECT COUNT(*) FROM advance_payment_allocations WHERE id=931") == 0
    assert _count(db, "SELECT COUNT(*) FROM quote_advance_schedules WHERE id=941") == 0
    assert _count(db, "SELECT COUNT(*) FROM job_deliverables WHERE id=951") == 0

    # SURVIVOR intatto
    assert _count(db, "SELECT COUNT(*) FROM invoices WHERE id=990") == 1
    assert _count(db, "SELECT COUNT(*) FROM advance_payments WHERE id=991") == 1
    assert _count(db, "SELECT COUNT(*) FROM quote_advance_schedules WHERE id=992") == 1
    assert _count(db, "SELECT COUNT(*) FROM job_deliverables WHERE id=993") == 1

    # report coerente
    assert res["invoices"] >= 2
    assert res["advance_payments"] >= 1
    assert res["job_deliverables"] >= 1


def test_purge_cascade_empty_safe(db):
    # Nessun dipendente → nessun errore, conteggi 0.
    res = _purge_project_dependents(db, project_id=12345, job_ids=[], quote_ids=[], jcl_ids=[])
    assert res["invoices"] == 0
    assert res["job_deliverables"] == 0
