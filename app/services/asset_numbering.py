"""v3.5.0-alpha.72.1 — Numerazione automatica asset fisici.

Setting per-tenant: `asset_numbering_config` JSON. Schema:
    {
      "LTO":   {"prefix": "LTO-",   "counter": 1, "pad": 3},
      "HDD":   {"prefix": "HDD-",   "counter": 1, "pad": 3},
      "CRU":   {"prefix": "CRU-",   "counter": 1, "pad": 3},
      "BLURAY":{"prefix": "BD-",    "counter": 1, "pad": 4},
    }

`next_label(db, kind)` ritorna stringa label generata e incrementa
counter atomicamente (commit). Idempotente NON: ogni call avanza.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from app.models import Tenant


DEFAULT_CONFIG = {
    "LTO":     {"prefix": "LTO-",     "counter": 1, "pad": 3},
    "HDD":     {"prefix": "HDD-",     "counter": 1, "pad": 3},
    "CRU":     {"prefix": "CRU-",     "counter": 1, "pad": 3},
    "BLURAY":  {"prefix": "BD-",      "counter": 1, "pad": 4},
    "DVD":     {"prefix": "DVD-",     "counter": 1, "pad": 4},
    "CASE":    {"prefix": "CASE-",    "counter": 1, "pad": 3},
    "OTHER":   {"prefix": "AST-",     "counter": 1, "pad": 4},
}


def get_config(db: Session, tenant_id: int = 1) -> dict:
    """Ritorna config corrente del tenant (merge default + override)."""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        return dict(DEFAULT_CONFIG)
    cfg = dict(DEFAULT_CONFIG)
    if t.asset_numbering_config:
        for k, v in (t.asset_numbering_config or {}).items():
            cfg[k.upper()] = v
    return cfg


def save_config(db: Session, new_config: dict, tenant_id: int = 1) -> dict:
    """Salva config (commit caller-side opt, qui flush only)."""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        raise ValueError("Tenant non trovato")
    # Validation: ogni voce deve avere prefix string + counter int + pad int
    clean = {}
    for k, v in (new_config or {}).items():
        if not isinstance(v, dict):
            continue
        key = str(k).upper()
        clean[key] = {
            "prefix": str(v.get("prefix") or "")[:20],
            "counter": int(v.get("counter") or 1),
            "pad": max(0, min(8, int(v.get("pad") or 3))),
        }
    t.asset_numbering_config = clean
    db.flush()
    return clean


def next_label(db: Session, kind: str, tenant_id: int = 1) -> Optional[str]:
    """Genera label da config per `kind`. Avanza counter (commit caller).
    Ritorna None se kind non configurato (caller usa fallback manuale).

    Note SQLA: JSON columns non rilevano mutation in-place. Costruiamo un
    nuovo dict ad ogni call e usiamo `flag_modified` per essere safe."""
    from sqlalchemy.orm.attributes import flag_modified
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        return None
    # Deep-copy il dict per non condividere references
    import copy as _copy
    cfg = _copy.deepcopy(dict(t.asset_numbering_config or {}))
    key = (kind or "").upper()
    default = DEFAULT_CONFIG.get(key)
    entry = cfg.get(key) or (_copy.deepcopy(default) if default else None)
    if not entry:
        return None
    prefix = entry.get("prefix", "")
    counter = int(entry.get("counter") or 1)
    pad = int(entry.get("pad") or 3)
    label = f"{prefix}{str(counter).zfill(pad)}"
    entry["counter"] = counter + 1
    cfg[key] = entry
    t.asset_numbering_config = cfg
    flag_modified(t, "asset_numbering_config")
    db.flush()
    return label


def peek_label(db: Session, kind: str, offset: int = 0, tenant_id: int = 1) -> Optional[str]:
    """Anteprima next label senza avanzare. Utile per UI batch import."""
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        return None
    cfg = dict(t.asset_numbering_config or {})
    key = (kind or "").upper()
    default = DEFAULT_CONFIG.get(key)
    entry = cfg.get(key) or (dict(default) if default else None)
    if not entry:
        return None
    counter = int(entry.get("counter") or 1) + offset
    pad = int(entry.get("pad") or 3)
    return f"{entry.get('prefix','')}{str(counter).zfill(pad)}"
