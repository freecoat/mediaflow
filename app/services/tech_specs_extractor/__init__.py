"""Bundle L Stack 1 — Registry + public API extractor service.

Plugin registry pattern: nuovi extractor si registrano via decorator
@register_extractor(name, mime_priority). Lookup via mime glob match.
"""
from __future__ import annotations

import fnmatch
import logging
from datetime import datetime
from typing import Optional, Type

from app.services.tech_specs_extractor.base import TechSpecsExtractor

logger = logging.getLogger(__name__)


# Registry: lista di tuple (mime_pattern, priority_index, extractor_class)
# Ordine di inserzione = priorità (first match wins all'interno della stessa
# mime_pattern). Per mime_priority diversi è possibile registrare lo stesso
# extractor su pattern multipli.
_REGISTRY: list[tuple[str, Type[TechSpecsExtractor]]] = []


def register_extractor(name: str, mime_priority: list[str]):
    """Decorator per registrare un extractor con mime patterns supportati.

    Esempio:
        @register_extractor(name="ffprobe", mime_priority=["video/*", "audio/*"])
        class FFProbeExtractor(TechSpecsExtractor): ...
    """
    def deco(cls: Type[TechSpecsExtractor]):
        cls.name = name
        for pattern in mime_priority:
            _REGISTRY.append((pattern, cls))
        return cls
    return deco


def get_extractor(mime: Optional[str]) -> Optional[Type[TechSpecsExtractor]]:
    """Trova primo extractor il cui mime_priority matcha il mime fornito."""
    if not mime:
        return None
    mime_norm = mime.split(";", 1)[0].strip().lower()
    for pattern, cls in _REGISTRY:
        if fnmatch.fnmatch(mime_norm, pattern.lower()):
            return cls
    return None


def extract_tech_specs(path: str, mime: Optional[str] = None) -> dict:
    """API pubblica: estrae tech specs da `path`. Sceglie extractor via mime.

    Sempre ritorna dict con 'tool', 'errors'. tool='none' se nessun extractor
    matcha. errors[] popolato in caso di failure (gentle fallback).
    """
    cls = get_extractor(mime)
    if cls is None:
        return {
            "tool": "none",
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "container": None, "video": None, "audio": [],
            "errors": [f"Nessun extractor registrato per mime '{mime}'"],
        }
    try:
        inst = cls()
        out = inst.extract(path, mime)
        out.setdefault("tool", cls.name)
        out.setdefault("extracted_at", datetime.utcnow().isoformat() + "Z")
        out.setdefault("errors", [])
        out.setdefault("audio", [])
        out.setdefault("video", None)
        out.setdefault("container", None)
        return out
    except Exception as e:
        logger.exception("extractor %s failed on %s", cls.name, path)
        return {
            "tool": cls.name,
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "container": None, "video": None, "audio": [],
            "errors": [f"extractor exception: {type(e).__name__}: {e}"],
        }


# Auto-load extractors (registry side-effect via @register_extractor decorator)
from app.services.tech_specs_extractor import ffprobe_extractor as _ffp  # noqa: F401, E402

