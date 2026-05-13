"""v3.5.0-alpha.92 — Seed simulato AssetMembership.

Popola AssetMembership con dati realistici per dimostrare la feature
"contenuti del supporto" sul modal PhysicalAsset:

- Scegli N physical asset (default 30) di tipo HDD/LTO/CRU
- Per ognuno aggiungi 3-10 digital asset come contenuti
- Mix di current (removed_at=NULL) e history (removed_at valorizzato)
- Path realistici (/DCP/, /MIX/, /MASTER/, /VFX/, ecc.)

Idempotente per default: salta physical asset che hanno già memberships.
"""

import os, sys, random
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import PhysicalAsset, Asset, AssetMembership, PhysicalAssetKind


PATHS_BY_KIND = {
    PhysicalAssetKind.lto:    ["/DPX_GRADED/", "/MASTER_DCDM/", "/MIX_5.1/", "/SUB_DELIVERY/", "/HEAD_FORMAT/"],
    PhysicalAssetKind.hdd:    ["/DCP/", "/MXF_PRORES/", "/MIX_STEREO/", "/CAPTIONS/", "/TEXTLESS/"],
    PhysicalAssetKind.cru:    ["/RAW_DAILIES/", "/SYNCED_FOOTAGE/", "/EDIT_PROJECT/"],
    PhysicalAssetKind.bluray: ["/BD25/", "/BD50/"],
    PhysicalAssetKind.dvd:    ["/DVD9/"],
    PhysicalAssetKind.case:   ["/PACKAGE/"],
}


def seed(target_count: int = 30, force: bool = False) -> dict:
    db: Session = SessionLocal()
    try:
        already = db.query(AssetMembership.physical_asset_id).distinct().all()
        already_ids = {a[0] for a in already}
        if already_ids and not force:
            print(f"⚠ {len(already_ids)} physical asset hanno già memberships. Uso --force per ri-seed.")
            print("Continuo aggiungendo solo a quelli che non ne hanno.")

        # Filtra physical asset attivi senza memberships, escludendo case (poca utilità)
        q = db.query(PhysicalAsset).filter(
            PhysicalAsset.deleted_at.is_(None),
            PhysicalAsset.kind != PhysicalAssetKind.case,
        )
        if not force:
            q = q.filter(~PhysicalAsset.id.in_(already_ids))
        pa_pool = q.limit(target_count * 3).all()  # pool ampio per random sample
        if not pa_pool:
            print("Nessun physical asset eleggibile.")
            return {"created": 0}

        # Sample target_count
        chosen = random.sample(pa_pool, min(target_count, len(pa_pool)))

        # Digital asset pool
        digital_pool = db.query(Asset).filter(Asset.tenant_id == 1).limit(2000).all()
        if not digital_pool:
            print("Nessun digital asset disponibile.")
            return {"created": 0}

        total_added = 0
        total_removed = 0
        now = datetime.utcnow()
        for pa in chosen:
            paths = PATHS_BY_KIND.get(pa.kind, ["/CONTENT/"])
            content_count = random.randint(3, 10)
            samples = random.sample(digital_pool, min(content_count, len(digital_pool)))
            # 60% present, 40% history (removed)
            for digital in samples:
                path = random.choice(paths)
                # Random added 1-180 giorni fa
                added_days = random.randint(7, 180)
                added_at = now - timedelta(days=added_days, hours=random.randint(0, 23))
                removed_at = None
                if random.random() < 0.4:
                    # Removed: rimosso 1-30 giorni dopo (ma non nel futuro)
                    rem_delta = random.randint(1, min(30, added_days))
                    removed_at = added_at + timedelta(days=rem_delta)
                    total_removed += 1
                else:
                    total_added += 1
                # Checksum simulato
                checksum = f"md5:{random.getrandbits(64):016x}"
                m = AssetMembership(
                    tenant_id=pa.tenant_id,
                    physical_asset_id=pa.id,
                    asset_id=digital.id,
                    path_on_media=path + digital.original_name,
                    checksum=checksum,
                    file_size=digital.file_size,
                    notes=None,
                    added_at=added_at,
                    removed_at=removed_at,
                )
                db.add(m)
        db.commit()
        print(f"✓ Seed completato:")
        print(f"  Physical asset popolati: {len(chosen)}")
        print(f"  Memberships create: {total_added + total_removed}")
        print(f"    · Presenti: {total_added}")
        print(f"    · Storico (rimossi): {total_removed}")
        return {
            "physical_assets_seeded": len(chosen),
            "memberships_present": total_added,
            "memberships_removed": total_removed,
        }
    finally:
        db.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    n = 30
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)
    seed(target_count=n, force=force)
