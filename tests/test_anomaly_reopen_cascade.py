"""Regressione cascade cleanup su reopen anomalia (F10 test plan).

Invariante finance (α.172.37, BLOCCO 4): riaprire un'anomalia handled deve
rimuovere il record P&L generato dal handle, altrimenti il re-handle crea un
SECONDO record → double-count in P&L.
  - write_off_loss → LossEntry: HARD delete
  - overhead_cost  → OverheadCost: SOFT delete (deleted_at, audit preservato)

Testato chiamando direttamente la coroutine reopen_anomaly con Request
fittizia + current_tenant_id monkeypatchato (stesso pattern dei test DAM).
"""
import asyncio
from datetime import datetime, date
from types import SimpleNamespace

from app.models import models as m
from app.routers import anomalies as anomalies_router


def _fake_request(user_id=1):
    return SimpleNamespace(state=SimpleNamespace(current_user=SimpleNamespace(id=user_id)))


def _mk_anomaly(db, *, target_kind, target_id, action):
    e = m.AnomalyEntry(
        tenant_id=1,
        anomaly_type=m.AnomalyType.quote_discrepancy,
        source_kind=m.AnomalySourceKind.jcl,
        source_id=1,
        dedup_key=f"test-{target_kind}-{target_id}",
        amount=1000.0,
        description="Test anomaly",
        detected_at=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
        status=m.AnomalyStatus.handled,
        handled_action=action,
        handled_at=datetime.utcnow(),
        handled_target_kind=target_kind,
        handled_target_id=target_id,
        project_id=1,
    )
    db.add(e)
    db.flush()
    return e


def test_reopen_hard_deletes_lossentry(db, monkeypatch):
    monkeypatch.setattr(anomalies_router, "current_tenant_id", lambda: 1)
    le = m.LossEntry(tenant_id=1, project_id=1, amount=1000.0,
                     reason=m.LossReason.written_off, created_at=datetime.utcnow())
    db.add(le)
    db.flush()
    le_id = le.id
    entry = _mk_anomaly(db, target_kind="LossEntry", target_id=le_id,
                        action=m.AnomalyAction.write_off_loss)

    res = asyncio.run(anomalies_router.reopen_anomaly(_fake_request(), entry.id, db))

    assert res["status"] == "open"
    assert "LossEntry#" in (res["target_cleanup"] or "")
    # HARD delete: il record non esiste più
    assert db.query(m.LossEntry).filter(m.LossEntry.id == le_id).first() is None
    db.refresh(entry)
    assert entry.status == m.AnomalyStatus.open
    assert entry.handled_action is None
    # handled_target_id resta per audit (puntatore al record cancellato)
    assert entry.handled_target_id == le_id


def test_reopen_soft_deletes_overheadcost(db, monkeypatch):
    monkeypatch.setattr(anomalies_router, "current_tenant_id", lambda: 1)
    cat = list(m.OverheadCostCategory)[0]
    oc = m.OverheadCost(
        tenant_id=1, code="OVH-TEST-1", category=cat, title="Test overhead",
        amount_net=1000.0, vat_rate=22.0, amount_vat=220.0, amount_total=1220.0,
        cost_date=date(2026, 5, 31), is_recurring=False, is_capex=False,
        created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
    )
    db.add(oc)
    db.flush()
    oc_id = oc.id
    entry = _mk_anomaly(db, target_kind="OverheadCost", target_id=oc_id,
                        action=m.AnomalyAction.overhead_cost)

    res = asyncio.run(anomalies_router.reopen_anomaly(_fake_request(), entry.id, db))

    assert res["status"] == "open"
    assert "OverheadCost#" in (res["target_cleanup"] or "")
    # SOFT delete: record esiste ma deleted_at valorizzato
    db.refresh(oc)
    assert oc.deleted_at is not None


def test_reopen_open_anomaly_is_noop(db, monkeypatch):
    monkeypatch.setattr(anomalies_router, "current_tenant_id", lambda: 1)
    entry = _mk_anomaly(db, target_kind="LossEntry", target_id=999,
                        action=m.AnomalyAction.write_off_loss)
    entry.status = m.AnomalyStatus.open
    db.flush()
    res = asyncio.run(anomalies_router.reopen_anomaly(_fake_request(), entry.id, db))
    assert res.get("noop") is True
