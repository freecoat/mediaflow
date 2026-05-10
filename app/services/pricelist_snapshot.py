"""
Backup/restore del listino prezzi.

Un PricelistSnapshot cristallizza l'intero listino di un tenant (departments
+ categories + items) in un payload JSON versionato. Permette:
  - backup manuale prima di modifiche aggressive
  - ripristino con modalità replace o merge
  - export/import file .json per portabilità tra installazioni
  - preset built-in caricati da app/data/pricelist_presets/

Schema del payload (v1.1):
{
  "schema_version": "1.1",
  "exported_at": "ISO datetime UTC",
  "exported_by": "email user (opzionale)",
  "source_app_version": "3.5.0-alpha.X",
  "tenant_id": int,
  "departments": [
    {"code", "name", "color", "sort_order", "description"}
  ],
  "categories": [
    {"name", "description", "sort_order"}
  ],
  "items": [
    {"category", "department_code", "name", "description",
     "unit_pre", "unit", "price_list", "price_average", "price_low",
     "hardcosts", "keywords": [...], "is_active": bool}
  ]
}

La v1.0 (schema legacy senza `departments`) è letta in input ma in output
esportiamo sempre v1.1.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
from sqlalchemy.orm import Session, joinedload

from app.models import (
    PriceCategory, PriceItem, Department,
    PricelistSnapshot, PricelistSnapshotKind,
)

CURRENT_SCHEMA_VERSION = "1.1"


def _app_version() -> str:
    try:
        from app.main import app  # type: ignore
        return getattr(app, "version", "unknown")
    except Exception:
        return "unknown"


# ── BUILD PAYLOAD ─────────────────────────────────────────────

def build_snapshot_payload(
    db: Session,
    tenant_id: int,
    exported_by_email: Optional[str] = None,
    include_inactive: bool = True,
) -> dict:
    """Estrae l'intero listino del tenant come dict serializzabile."""
    deps = (
        db.query(Department)
        .filter(Department.tenant_id == tenant_id)
        .order_by(Department.sort_order, Department.name)
        .all()
    )
    cats = (
        db.query(PriceCategory)
        .filter(PriceCategory.tenant_id == tenant_id)
        .order_by(PriceCategory.sort_order, PriceCategory.name)
        .all()
    )
    q = db.query(PriceItem).options(
        joinedload(PriceItem.category),
        joinedload(PriceItem.department),
    ).filter(PriceItem.tenant_id == tenant_id)
    if not include_inactive:
        q = q.filter(PriceItem.is_active == True)
    items = q.order_by(PriceItem.id).all()

    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "exported_by": exported_by_email,
        "source_app_version": _app_version(),
        "tenant_id": tenant_id,
        "departments": [
            {
                "code": d.code,
                "name": d.name,
                "color": d.color,
                "sort_order": d.sort_order,
                "description": d.description,
            }
            for d in deps
        ],
        "categories": [
            {
                "name": c.name,
                "description": c.description,
                "sort_order": c.sort_order,
            }
            for c in cats
        ],
        "items": [
            {
                "category": it.category.name if it.category else None,
                "department_code": it.department.code if it.department else None,
                "name": it.name,
                "description": it.description,
                "unit_pre": it.unit_pre,
                "unit": it.unit,
                "price_list": it.price_list,
                "price_average": it.price_average,
                "price_low": it.price_low,
                "hardcosts": it.hardcosts,
                "keywords": it.keywords or [],
                "is_active": it.is_active,
            }
            for it in items
        ],
    }


# ── APPLY PAYLOAD ─────────────────────────────────────────────

ApplyMode = Literal["replace", "merge"]


def apply_snapshot_payload(
    db: Session,
    tenant_id: int,
    payload: dict,
    mode: ApplyMode = "merge",
    auto_backup: bool = True,
    auto_backup_user_id: Optional[int] = None,
) -> dict:
    """Applica un payload al listino del tenant.

    mode = "merge"   → categorie/voci con stesso nome aggiornate; nuove aggiunte;
                       le esistenti non in payload preservate. Reparti idem.
    mode = "replace" → DELETE di tutte le voci e categorie del tenant, poi
                       importa. I reparti vengono comunque mergiati per nome
                       (non eliminati: hanno ref da risorse).

    Se `auto_backup=True` E mode='replace', crea PRIMA un PricelistSnapshot
    di tipo `auto` con il listino corrente, per permettere rollback.

    Restituisce un dict con stats (categories_created, items_created/updated/skipped, ecc.).
    """
    if mode not in ("merge", "replace"):
        raise ValueError(f"mode deve essere 'merge' o 'replace', ricevuto {mode!r}")

    if not isinstance(payload, dict) or "items" not in payload:
        raise ValueError("Payload non riconosciuto: manca il campo 'items'")

    stats = {
        "mode": mode,
        "auto_backup_id": None,
        "departments_created": 0,
        "departments_updated": 0,
        "categories_created": 0,
        "categories_updated": 0,
        "categories_deleted": 0,
        "items_created": 0,
        "items_updated": 0,
        "items_skipped": 0,
        "items_deleted": 0,
    }

    # 1) Auto-backup pre-replace (sicurezza)
    if mode == "replace" and auto_backup:
        backup = create_snapshot_record(
            db,
            tenant_id=tenant_id,
            name=f"Auto-backup pre-replace {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
            description="Snapshot automatico creato prima di un restore in modalità 'replace'.",
            kind=PricelistSnapshotKind.auto,
            user_id=auto_backup_user_id,
        )
        db.flush()
        stats["auto_backup_id"] = backup.id

    # 2) Reparti (merge per code, mai cancellati)
    dep_map: dict[str, int] = {}
    for d_data in payload.get("departments", []) or []:
        code = d_data.get("code")
        if not code:
            continue
        existing_d = (
            db.query(Department)
            .filter(Department.tenant_id == tenant_id, Department.code == code)
            .first()
        )
        if existing_d:
            existing_d.name = d_data.get("name") or existing_d.name
            if d_data.get("color"):
                existing_d.color = d_data["color"]
            if d_data.get("sort_order") is not None:
                existing_d.sort_order = d_data["sort_order"]
            if d_data.get("description") is not None:
                existing_d.description = d_data["description"]
            dep_map[code] = existing_d.id
            stats["departments_updated"] += 1
        else:
            new_d = Department(
                tenant_id=tenant_id,
                code=code,
                name=d_data.get("name") or code,
                color=d_data.get("color") or "#6272f5",
                sort_order=d_data.get("sort_order") or 100,
                description=d_data.get("description"),
            )
            db.add(new_d); db.flush()
            dep_map[code] = new_d.id
            stats["departments_created"] += 1

    # Includi anche reparti già esistenti non presenti nel payload (per assegnamento voci)
    for d in db.query(Department).filter(Department.tenant_id == tenant_id).all():
        dep_map.setdefault(d.code, d.id)

    # 3) Replace: cancella voci e categorie esistenti
    if mode == "replace":
        deleted_items = (
            db.query(PriceItem).filter(PriceItem.tenant_id == tenant_id).delete()
        )
        cat_ids = [
            c.id for c in db.query(PriceCategory)
            .filter(PriceCategory.tenant_id == tenant_id).all()
        ]
        deleted_cats = 0
        for cid in cat_ids:
            db.query(PriceCategory).filter(PriceCategory.id == cid).delete()
            deleted_cats += 1
        db.flush()
        stats["items_deleted"] = deleted_items
        stats["categories_deleted"] = deleted_cats

    # 4) Categorie (merge per name)
    cat_map: dict[str, int] = {}
    for c_data in payload.get("categories", []) or []:
        name = c_data.get("name")
        if not name:
            continue
        existing_c = (
            db.query(PriceCategory)
            .filter(PriceCategory.tenant_id == tenant_id, PriceCategory.name == name)
            .first()
        )
        if existing_c:
            if c_data.get("description") is not None:
                existing_c.description = c_data["description"]
            if c_data.get("sort_order") is not None:
                existing_c.sort_order = c_data["sort_order"]
            cat_map[name] = existing_c.id
            stats["categories_updated"] += 1
        else:
            new_c = PriceCategory(
                tenant_id=tenant_id,
                name=name,
                description=c_data.get("description"),
                sort_order=c_data.get("sort_order") or 100,
            )
            db.add(new_c); db.flush()
            cat_map[name] = new_c.id
            stats["categories_created"] += 1

    # Categorie residue (esistenti non in payload)
    for c in db.query(PriceCategory).filter(PriceCategory.tenant_id == tenant_id).all():
        cat_map.setdefault(c.name, c.id)

    # 5) Voci listino
    for it_data in payload.get("items", []) or []:
        cat_name = it_data.get("category")
        cat_id = cat_map.get(cat_name) if cat_name else None
        if not cat_id:
            stats["items_skipped"] += 1
            continue

        name = it_data.get("name")
        if not name:
            stats["items_skipped"] += 1
            continue

        dep_code = it_data.get("department_code")
        dep_id = dep_map.get(dep_code) if dep_code else None

        existing_it = (
            db.query(PriceItem)
            .filter(
                PriceItem.tenant_id == tenant_id,
                PriceItem.category_id == cat_id,
                PriceItem.name == name,
            )
            .first()
        )

        if existing_it and mode == "merge":
            existing_it.description = it_data.get("description")
            existing_it.unit_pre = it_data.get("unit_pre", "per")
            existing_it.unit = it_data.get("unit", "day")
            existing_it.price_list = it_data.get("price_list")
            existing_it.price_average = it_data.get("price_average")
            existing_it.price_low = it_data.get("price_low")
            existing_it.hardcosts = it_data.get("hardcosts")
            existing_it.keywords = it_data.get("keywords") or []
            existing_it.department_id = dep_id
            existing_it.is_active = it_data.get("is_active", True)
            stats["items_updated"] += 1
        else:
            db.add(PriceItem(
                tenant_id=tenant_id,
                category_id=cat_id,
                department_id=dep_id,
                name=name,
                description=it_data.get("description"),
                unit_pre=it_data.get("unit_pre", "per"),
                unit=it_data.get("unit", "day"),
                price_list=it_data.get("price_list"),
                price_average=it_data.get("price_average"),
                price_low=it_data.get("price_low"),
                hardcosts=it_data.get("hardcosts"),
                keywords=it_data.get("keywords") or [],
                is_active=it_data.get("is_active", True),
            ))
            stats["items_created"] += 1

    return stats


# ── SNAPSHOT RECORDS (DB) ─────────────────────────────────────

def create_snapshot_record(
    db: Session,
    tenant_id: int,
    name: str,
    description: Optional[str],
    kind: PricelistSnapshotKind = PricelistSnapshotKind.manual,
    user_id: Optional[int] = None,
    payload: Optional[dict] = None,
    user_email: Optional[str] = None,
) -> PricelistSnapshot:
    """Crea un record `PricelistSnapshot` nel DB.

    Se `payload` è None, lo costruisce dal listino corrente del tenant.
    Se passato esplicitamente (es. import da file), lo salva come-is.
    """
    if payload is None:
        payload = build_snapshot_payload(db, tenant_id, exported_by_email=user_email)

    snap = PricelistSnapshot(
        tenant_id=tenant_id,
        name=name.strip()[:255],
        description=(description or "").strip() or None,
        kind=kind,
        item_count=len(payload.get("items", []) or []),
        category_count=len(payload.get("categories", []) or []),
        department_count=len(payload.get("departments", []) or []),
        schema_version=payload.get("schema_version", CURRENT_SCHEMA_VERSION),
        source_app_version=payload.get("source_app_version") or _app_version(),
        payload_json=payload,
        created_by_user_id=user_id,
    )
    db.add(snap); db.flush()
    return snap


def list_snapshots(
    db: Session,
    tenant_id: int,
    include_deleted: bool = False,
    kinds: Optional[list[PricelistSnapshotKind]] = None,
) -> list[PricelistSnapshot]:
    q = db.query(PricelistSnapshot).filter(PricelistSnapshot.tenant_id == tenant_id)
    if not include_deleted:
        q = q.filter(PricelistSnapshot.deleted_at.is_(None))
    if kinds:
        q = q.filter(PricelistSnapshot.kind.in_(kinds))
    return q.order_by(PricelistSnapshot.created_at.desc()).all()


def soft_delete_snapshot(db: Session, snap: PricelistSnapshot) -> None:
    snap.deleted_at = datetime.utcnow()


def restore_deleted_snapshot(db: Session, snap: PricelistSnapshot) -> None:
    snap.deleted_at = None


def hard_delete_snapshot(db: Session, snap: PricelistSnapshot) -> None:
    db.delete(snap)


# ── PRESET FILES (built-in committed in repo) ─────────────────

def _presets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "pricelist_presets"


def list_preset_files() -> list[Path]:
    d = _presets_dir()
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.json") if p.is_file())


def load_preset_payload(preset_filename: str) -> dict:
    """Carica un file preset committato in app/data/pricelist_presets/."""
    safe_name = Path(preset_filename).name  # blocca path traversal
    path = _presets_dir() / safe_name
    if not path.exists() or path.suffix != ".json":
        raise FileNotFoundError(f"Preset {safe_name!r} non trovato")
    return json.loads(path.read_text(encoding="utf-8"))
