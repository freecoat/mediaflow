"""v3.5.0-alpha.172.178 — Reject "progetto perso" (mode=lost) su quote approvata.

Pulisce job + acconti pending SE nulla è fatturato/lavorato; BLOCCA (409) se ci sono
acconti fatturati/pagati o fatture emesse (scelta Matteo: gestisci prima note credito).
"""
import asyncio
import pytest
from sqlalchemy import text
from fastapi import HTTPException
from app.models.models import QuoteStatus
from app.routers.quotes import update_quote_status

C = "'2026-01-01 00:00:00'"


def _seed_graph(db):
    db.execute(text(f"INSERT INTO projects (id,tenant_id,code,title,client_id,status,created_at,updated_at,mfa_required,billing_frequency,shipping_markup_pct,finance_status) VALUES (99,1,'P99','Proj',1,'active',{C},{C},0,'monthly',15,'active')"))
    db.execute(text(f"INSERT INTO quotes (id,tenant_id,number,version,project_id,client_id,title,status,issue_date,package_discount,vat_rate,shipping_markup_pct,currency,fx_rate_to_base,subtotal_gross,subtotal,total_after_discount,total_with_vat,subtotal_gross_jcl,subtotal_gross_deliverable,generated_from_deliverables,created_at,is_phantom) VALUES (500,1,'Q-500',1,99,1,'Q','approved','2026-01-01',0,22,15,'EUR',1,1000,1000,1000,1220,1000,0,0,{C},0)"))
    db.execute(text(f"INSERT INTO jobs (id,tenant_id,code,title,project_id,client_id,quote_id,status,budget_quoted,weighted_revenue,created_at) VALUES (200,1,'J200','Job',99,1,500,'active',1000,0,{C})"))
    db.execute(text("INSERT INTO job_cost_lines (id,tenant_id,job_id,description,quantity_quoted,quantity_actual,unit,unit_price,total_quoted,total_accrued,total_expected,is_billable,total_cost_accrued,total_cost_external,accrued_stale,external_outsourced,is_extra,billing_status) VALUES (300,1,200,'CL',1,0,'day',1000,1000,0,1000,1,0,0,0,0,0,'not_billed')"))
    db.flush()


def _add_advance(db, aid, status, invoice_id="NULL"):
    db.execute(text(f"INSERT INTO advance_payments (id,tenant_id,project_id,amount,balance_remaining,status,created_at,invoice_id) VALUES ({aid},1,99,500,500,'{status}',{C},{invoice_id})"))
    db.flush()


def _call_lost(db):
    return asyncio.run(update_quote_status(
        quote_id=500, status=QuoteStatus.rejected, mode="lost", db=db))


def test_lost_clean_cancels_job_and_pending_advances(db):
    _seed_graph(db)
    _add_advance(db, 400, "pending")
    res = _call_lost(db)
    assert str(res["status"]) in ("QuoteStatus.rejected", "rejected")
    assert db.execute(text("SELECT status FROM quotes WHERE id=500")).scalar() == "rejected"
    assert db.execute(text("SELECT status FROM jobs WHERE id=200")).scalar() == "cancelled"
    assert db.execute(text("SELECT status FROM advance_payments WHERE id=400")).scalar() == "cancelled"


def test_lost_blocked_if_advance_invoiced(db):
    _seed_graph(db)
    _add_advance(db, 401, "invoiced")
    with pytest.raises(HTTPException) as ei:
        _call_lost(db)
    assert ei.value.status_code == 409
    assert "fatturat" in ei.value.detail.lower()
    # nulla cambiato
    assert db.execute(text("SELECT status FROM quotes WHERE id=500")).scalar() == "approved"
    assert db.execute(text("SELECT status FROM jobs WHERE id=200")).scalar() == "active"
