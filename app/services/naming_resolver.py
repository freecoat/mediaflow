"""Naming convention strutturata — schema, normalizzazione, risoluzione a cascata.

Gerarchia override (per ogni deliverable/asset):
    item.naming_convention -> template.naming_convention -> tenant.naming_conventions[discipline]
    -> DEFAULT_TENANT_NAMING_CONVENTIONS[discipline] (costante industry, ultimo fallback).

Schema <conv>: {pattern, tokens[], separator, allowed_chars, max_length, case,
extension, examples[], source, raw_note, unknown_tokens[]}.
Token ammessi = naming_helper.KNOWN_TOKENS. La verifica del filename asset NON è qui (backlog QC).
"""
from __future__ import annotations
from typing import Optional

from app.services.naming_helper import KNOWN_TOKENS

_CASES = {"upper", "lower", "asis"}

DEFAULT_TENANT_NAMING_CONVENTIONS: dict = {
    "video": {
        "pattern": "{project_code}_{film_name}_{deliverable_kind}_{resolution}_{lang_audio}_{date_compact}",
        "tokens": ["project_code", "film_name", "deliverable_kind", "resolution", "lang_audio", "date_compact"],
        "separator": "_",
        "allowed_chars": "A-Za-z0-9_-",
        "max_length": 120,
        "case": "asis",
        "extension": "",
        "examples": ["MARE-2026_MareNostrum_PRORES_UHD_it_20260612.mov"],
        "source": "tenant_default",
        "raw_note": "Default azienda video (ispirato a ISDCF DCP / Netflix archival).",
    },
    "audio": {
        "pattern": "{project_code}_{film_name}_{audio_config}_{lang_audio}_{date_compact}",
        "tokens": ["project_code", "film_name", "audio_config", "lang_audio", "date_compact"],
        "separator": "_",
        "allowed_chars": "A-Za-z0-9_-",
        "max_length": 120,
        "case": "asis",
        "extension": "",
        "examples": ["MARE-2026_MareNostrum_51_it_20260612.wav"],
        "source": "tenant_default",
        "raw_note": "Default azienda audio.",
    },
}


def normalize_naming_convention(raw: Optional[dict]) -> Optional[dict]:
    """Valida/ripulisce un dict naming convention (output AI o form).
    Ritorna None se vuoto o privo di pattern E raw_note. Non solleva: difensivo."""
    if not raw or not isinstance(raw, dict):
        return None
    pattern = (raw.get("pattern") or "").strip()
    raw_note = (raw.get("raw_note") or "").strip()
    if not pattern and not raw_note:
        return None
    tokens = raw.get("tokens") or []
    if not isinstance(tokens, list):
        tokens = []
    tokens = [str(t).strip() for t in tokens if str(t).strip()]
    unknown = [t for t in tokens if t not in KNOWN_TOKENS]
    case = str(raw.get("case") or "asis").strip().lower()
    if case not in _CASES:
        case = "asis"
    ml = raw.get("max_length")
    try:
        max_length = int(ml) if ml is not None and str(ml).strip() != "" else None
    except (TypeError, ValueError):
        max_length = None
    examples = raw.get("examples") or []
    if not isinstance(examples, list):
        examples = []
    examples = [str(e).strip() for e in examples if str(e).strip()]
    return {
        "pattern": pattern,
        "tokens": tokens,
        "separator": str(raw.get("separator") or "_"),
        "allowed_chars": str(raw.get("allowed_chars") or "A-Za-z0-9_-"),
        "max_length": max_length,
        "case": case,
        "extension": str(raw.get("extension") or ""),
        "examples": examples,
        "source": str(raw.get("source") or "manual"),
        "raw_note": raw_note,
        "unknown_tokens": unknown,
    }


def _pick_for_discipline(conv: Optional[dict], discipline: str) -> Optional[dict]:
    """Una <conv> può essere singola o dict per-disciplina {video,audio}."""
    if not conv or not isinstance(conv, dict):
        return None
    if "pattern" not in conv and (discipline in conv):
        return conv.get(discipline)
    if "pattern" in conv:
        return conv
    return None


def resolve_naming_convention(
    db=None,
    *,
    delivery_item=None,
    delivery_template=None,
    delivery_item_conv: Optional[dict] = None,
    delivery_template_conv: Optional[dict] = None,
    discipline: str = "video",
    tenant_naming: Optional[dict] = None,
) -> dict:
    """Risolve la naming convention applicabile per cascata. Ritorna SEMPRE un
    dict <conv> con chiave extra `_source` ('item'|'capitolato'|'tenant'|'tenant_default')."""
    discipline = (discipline or "video").strip().lower()
    if discipline not in ("video", "audio"):
        discipline = "video"

    item_conv = delivery_item_conv
    if item_conv is None and delivery_item is not None:
        item_conv = getattr(delivery_item, "naming_convention", None)
    tpl_conv = delivery_template_conv
    if tpl_conv is None and delivery_template is not None:
        tpl_conv = getattr(delivery_template, "naming_convention", None)

    picked = _pick_for_discipline(item_conv, discipline)
    if picked and picked.get("pattern"):
        return {**picked, "_source": "item"}
    picked = _pick_for_discipline(tpl_conv, discipline)
    if picked and picked.get("pattern"):
        return {**picked, "_source": "capitolato"}
    if tenant_naming and isinstance(tenant_naming, dict):
        tconv = tenant_naming.get(discipline)
        if tconv and tconv.get("pattern"):
            return {**tconv, "_source": "tenant"}
    return {**DEFAULT_TENANT_NAMING_CONVENTIONS[discipline], "_source": "tenant_default"}
