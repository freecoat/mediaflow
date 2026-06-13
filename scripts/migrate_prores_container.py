"""Backfill non distruttivo: DeliveryItem con codec famiglia ProRes e
container_id NULL → assegna il container QuickTime del loro tenant.

Idempotente: salta gli item che hanno già un container. Logga il conteggio.
Prerequisito: esiste un Container QuickTime/.mov attivo per il tenant; se manca
lo crea (name 'QuickTime', extension '.mov', media_kind 'video').

Uso:
    .venv\\Scripts\\python.exe scripts\\migrate_prores_container.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models.models import DeliveryItem, VideoCodec, Container


def _find_or_create_quicktime(db, tenant_id):
    q = (
        db.query(Container)
        .filter(Container.is_active == True)  # noqa: E712
        .order_by(Container.sort_order, Container.name)
    )
    if tenant_id is not None:
        q = q.filter((Container.tenant_id == tenant_id) | (Container.tenant_id.is_(None)))
    for c in q.all():
        nm = (c.name or "").strip().lower()
        ex = (c.extension or "").strip().lower()
        if "quicktime" in nm or "mov" in nm or ex in (".mov", "mov"):
            return c
    c = Container(
        tenant_id=tenant_id, name="QuickTime", extension=".mov",
        media_kind="video", is_active=True, sort_order=0,
        description="Auto-creato da migrate_prores_container",
    )
    db.add(c)
    db.flush()
    return c


def main():
    db = SessionLocal()
    try:
        prores_ids = {
            vc.id for vc in db.query(VideoCodec).all()
            if "prores" in ((vc.family or "").strip().lower())
        }
        if not prores_ids:
            print("Nessun VideoCodec ProRes in tassonomia: niente da fare.")
            return
        items = (
            db.query(DeliveryItem)
            .filter(
                DeliveryItem.video_codec_id.in_(prores_ids),
                DeliveryItem.container_id.is_(None),
            )
            .all()
        )
        if not items:
            print("Nessun DeliveryItem ProRes senza container. OK.")
            return
        touched = 0
        qt_by_tenant = {}
        for it in items:
            tid = getattr(it, "tenant_id", None)
            qt = qt_by_tenant.get(tid)
            if qt is None:
                qt = _find_or_create_quicktime(db, tid)
                qt_by_tenant[tid] = qt
            it.container_id = qt.id
            touched += 1
        db.commit()
        print(f"Backfill completato: {touched} DeliveryItem ProRes → QuickTime.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
