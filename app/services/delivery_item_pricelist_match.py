"""v3.5.0-alpha.172.122 (Tier 3 Bundle C) — AI matching DeliveryItem ↔ PriceItem.

Dato un DeliveryItem (con package/container/codec/resolution + name),
suggerisce le top N voci di listino candidate per linking
``suggested_price_item_id``.

Strategia:
- Pre-filtro deterministico: solo PriceItem attivi del tenant, opzionale
  filtro keyword overlap per ridurre N (sottocampione per LLM).
- LLM (Claude Sonnet 4.6 default): ranking ranked di top 3 con
  ``confidence`` 0..1 + reason testuale breve.
- Fallback no-AI: ranking heuristic per overlap keyword.
"""
from __future__ import annotations
import json
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.models import (
    DeliveryItem, PriceItem, PriceCategory, Package, Container,
    VideoCodec, Resolution,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Sei un esperto di post-produzione audiovisiva. Devi associare
un DeliveryItem (specifica tecnica di consegna) alla voce di listino
prezzi più appropriata.

Ricevi:
- Un DeliveryItem con specs (package, container, codec, resolution, audio).
- Lista di PriceItem candidati con (id, name, description, category, keywords).

Restituisci JSON {"matches": [...]} con UP TO 3 candidati ranked per pertinenza,
ognuno con:
- "price_item_id": int (PK PriceItem)
- "confidence": float 0..1 (1 = match perfetto, 0.5 = ragionevole, <0.3 = debole)
- "reason": stringa breve italiana (max 80 char) che spiega il match

REGOLE:
1. Match semantico sul DOMINIO (es. "Color HDR" matcha "Color grading HDR" anche se nome non identico).
2. Match strutturale: voce "DCP mastering" matcha item con package=DCP.
3. Match per keyword: cerca overlap parole chiave.
4. NON inventare price_item_id non presenti nella lista.
5. Se nessuno è ragionevole, ritorna lista vuota {"matches": []}.
"""


def _serialize_item_for_ai(db: Session, it: DeliveryItem) -> dict:
    """Riduce DeliveryItem a campi salienti per prompt LLM."""
    def _name(M, fk):
        if not fk:
            return None
        rec = db.get(M, fk)
        return rec.name if rec else None
    return {
        "name": it.name,
        "package": _name(Package, it.package_id),
        "container": _name(Container, it.container_id),
        "video_codec": _name(VideoCodec, it.video_codec_id),
        "resolution": _name(Resolution, it.resolution_id),
        "hdr_format": it.hdr_format,
        "color_space": it.color_space,
        "subtitle_format": it.subtitle_format,
        "notes": it.notes,
    }


def _serialize_price_items(db: Session, tenant_id: int, max_n: int = 120) -> list[dict]:
    """Carica PriceItem attivi del tenant. Limita per evitare prompt enormi."""
    rows = (
        db.query(PriceItem, PriceCategory.name)
        .join(PriceCategory, PriceItem.category_id == PriceCategory.id)
        .filter(PriceItem.tenant_id == tenant_id, PriceItem.is_active == True)  # noqa: E712
        .order_by(PriceItem.name.asc())
        .limit(max_n)
        .all()
    )
    out = []
    for pi, cat_name in rows:
        out.append({
            "id": pi.id,
            "name": pi.name,
            "description": (pi.description or "")[:160],
            "category": cat_name,
            "keywords": pi.keywords or [],
            "unit": pi.unit,
        })
    return out


def match_pricelist_for_item(
    db: Session, item: DeliveryItem, tenant_id: int, provider,
    max_candidates: int = 120,
) -> dict:
    """Ritorna dict {matches: [{price_item_id, confidence, reason, ...}]}.

    Se provider è None, fallback heuristic (overlap keyword)."""
    item_data = _serialize_item_for_ai(db, item)
    candidates = _serialize_price_items(db, tenant_id, max_n=max_candidates)

    if not candidates:
        return {"matches": [], "diag": "no PriceItem nel listino"}

    if provider is None:
        # Fallback heuristic: token overlap nome + keywords item vs candidati.
        return _heuristic_match(item_data, candidates)

    user_msg = f"""DeliveryItem da matchare:
{json.dumps(item_data, ensure_ascii=False, indent=2)}

PriceItem candidati ({len(candidates)} voci listino attive):
{json.dumps(candidates, ensure_ascii=False, indent=1)}

Ranka i top 3 più pertinenti."""

    try:
        result = provider.extract_json(SYSTEM_PROMPT, user_msg, max_tokens=2000)
    except Exception as e:
        logger.error(f"AI matching failed: {e}")
        return _heuristic_match(item_data, candidates)

    if not result or "matches" not in result:
        return _heuristic_match(item_data, candidates)

    # Arricchisce con dati listino per UI
    pi_map = {p["id"]: p for p in candidates}
    enriched = []
    for m in result.get("matches", [])[:3]:
        pid = m.get("price_item_id")
        if pid not in pi_map:
            continue
        p = pi_map[pid]
        enriched.append({
            "price_item_id": pid,
            "confidence": float(m.get("confidence", 0.0)),
            "reason": (m.get("reason") or "")[:160],
            "name": p["name"],
            "category": p["category"],
            "unit": p["unit"],
        })
    return {"matches": enriched, "diag": f"AI ranked {len(enriched)} su {len(candidates)} candidati"}


def _heuristic_match(item_data: dict, candidates: list[dict]) -> dict:
    """Fallback senza AI: overlap parole nome + keyword."""
    def _tokens(s: str) -> set[str]:
        return {t for t in (s or "").lower().replace("/", " ").replace("-", " ").split() if len(t) >= 3}

    item_tokens = _tokens(item_data.get("name", "")) | _tokens(item_data.get("package") or "") | _tokens(item_data.get("container") or "")
    scored = []
    for c in candidates:
        kw = " ".join((c.get("keywords") or []))
        c_tokens = _tokens(c["name"]) | _tokens(c.get("description", "")) | _tokens(kw) | _tokens(c.get("category", ""))
        overlap = item_tokens & c_tokens
        if not overlap:
            continue
        score = len(overlap) / max(len(item_tokens) or 1, 1)
        scored.append({
            "price_item_id": c["id"],
            "confidence": min(1.0, round(score, 2)),
            "reason": f"Overlap parole: {', '.join(sorted(overlap)[:5])}",
            "name": c["name"],
            "category": c["category"],
            "unit": c["unit"],
        })
    scored.sort(key=lambda x: x["confidence"], reverse=True)
    return {"matches": scored[:3], "diag": f"Heuristic match {len(scored)} candidati pertinenti su {len(candidates)} totali"}
