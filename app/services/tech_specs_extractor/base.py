"""Bundle L Stack 1 — ABC per tech specs extractor pluggable.

Ogni extractor (ffprobe, mediainfo, ai_vision) implementa `extract(path, mime)`
ritornando dict con shape canonica (subset di JSON Schema variant_v1).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class TechSpecsExtractor(ABC):
    """Base ABC. Sub-class implementa extract() per uno specifico tool/mime."""

    name: str = "abstract"

    @abstractmethod
    def extract(self, path: str, mime: Optional[str] = None) -> dict:
        """Estrae tech specs da file. Ritorna dict con almeno 'tool' e 'errors'.

        Shape canonica (subset variant_v1):
            {
              "tool": str,
              "container": {...} | None,
              "video": {...} | None,
              "audio": [...],
              "errors": [str, ...]
            }
        """
        ...
