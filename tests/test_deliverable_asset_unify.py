"""v3.5.0-alpha.172.206 — Unificazione link deliverable↔asset (audit B).

Verifica il servizio centrale: pivot = fonte di verità, FK cache sempre
sincronizzati (primario = ultimo confermato, escluso qc_report), dedup,
unlink, e il ponte AssetMembership→deliverable.
"""
from app.models.models import (
    JobDeliverable, Asset, PhysicalAsset, AssetMembership, DeliverableAsset,
    PhysicalAssetKind,
)
from app.services.deliverable_assets import (
    link_asset, unlink_asset, deliverables_served_by_physical,
)


def _deliverable(db, tenant_id, name="D"):
    d = JobDeliverable(tenant_id=tenant_id, job_id=1, name=name)
    db.add(d); db.flush()
    return d


def _physical(db, tenant_id, label="LTO-1"):
    p = PhysicalAsset(tenant_id=tenant_id, label=label, kind=PhysicalAssetKind.lto)
    db.add(p); db.flush()
    return p


def _asset(db, tenant_id, name="file.mxf"):
    a = Asset(
        tenant_id=tenant_id, filename=name, original_name=name,
        file_path="/tmp/" + name, asset_type="other", mime_type="application/octet-stream",
        file_size=1, uploaded_by=1,
    )
    db.add(a); db.flush()
    return a


def test_link_physical_syncs_primary(db, tenant_id):
    d = _deliverable(db, tenant_id)
    p = _physical(db, tenant_id)
    link_asset(db, d, physical_asset_id=p.id, source="manual")
    db.flush()
    assert d.physical_asset_id == p.id
    assert d.asset_locked_at is not None
    assert db.query(DeliverableAsset).filter_by(job_deliverable_id=d.id).count() == 1
    row = db.query(DeliverableAsset).filter_by(job_deliverable_id=d.id).first()
    assert row.tenant_id == tenant_id


def test_primary_is_latest_confirmed(db, tenant_id):
    d = _deliverable(db, tenant_id)
    p1 = _physical(db, tenant_id, "LTO-master")
    p2 = _physical(db, tenant_id, "LTO-clone")
    link_asset(db, d, physical_asset_id=p1.id, source="manual")
    link_asset(db, d, physical_asset_id=p2.id, source="manual")  # più recente
    db.flush()
    # entrambe le righe pivot esistono, ma il primario in cache = l'ultima
    assert db.query(DeliverableAsset).filter_by(job_deliverable_id=d.id).count() == 2
    assert d.physical_asset_id == p2.id


def test_dedup_no_duplicate_rows(db, tenant_id):
    d = _deliverable(db, tenant_id)
    p = _physical(db, tenant_id)
    link_asset(db, d, physical_asset_id=p.id, source="manual")
    link_asset(db, d, physical_asset_id=p.id, source="mhl_yoyotta")  # stesso asset
    db.flush()
    rows = db.query(DeliverableAsset).filter_by(job_deliverable_id=d.id).all()
    assert len(rows) == 1
    assert rows[0].source == "mhl_yoyotta"  # aggiornata, non duplicata


def test_qc_report_source_not_primary(db, tenant_id):
    d = _deliverable(db, tenant_id)
    a_qc = _asset(db, tenant_id, "qc.pdf")
    a_real = _asset(db, tenant_id, "master.mxf")
    link_asset(db, d, asset_id=a_qc.id, source="qc_report")
    db.flush()
    assert d.digital_asset_id is None  # qc_report non è primario
    link_asset(db, d, asset_id=a_real.id, source="manual")
    db.flush()
    assert d.digital_asset_id == a_real.id


def test_unlink_resyncs(db, tenant_id):
    d = _deliverable(db, tenant_id)
    p = _physical(db, tenant_id)
    link_asset(db, d, physical_asset_id=p.id, source="manual")
    db.flush()
    assert d.physical_asset_id == p.id
    n = unlink_asset(db, d, physical_asset_id=p.id)
    db.flush()
    assert n == 1
    assert d.physical_asset_id is None
    assert d.asset_locked_at is None


def test_served_by_physical_direct_and_transitive(db, tenant_id):
    # diretto: d1 linkato al nastro via pivot physical
    d1 = _deliverable(db, tenant_id, "direct")
    p = _physical(db, tenant_id, "LTO-7")
    link_asset(db, d1, physical_asset_id=p.id, source="manual")
    # transitivo: file sul nastro (Membership) → asset → pivot di d2
    d2 = _deliverable(db, tenant_id, "via-file")
    a = _asset(db, tenant_id, "ep01.mxf")
    db.add(AssetMembership(tenant_id=tenant_id, physical_asset_id=p.id, asset_id=a.id))
    link_asset(db, d2, asset_id=a.id, source="manual")
    db.flush()
    served = deliverables_served_by_physical(db, p.id, tenant_id)
    ids = {s["deliverable"].id for s in served}
    assert d1.id in ids and d2.id in ids
    by_id = {s["deliverable"].id: s["link_types"] for s in served}
    assert "diretto" in by_id[d1.id]
    assert "via file" in by_id[d2.id]
