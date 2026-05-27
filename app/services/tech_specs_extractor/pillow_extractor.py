"""Bundle L Stack 1 — PillowExtractor: fallback per immagini (image/*).

Usa Pillow (gia' nelle deps tramite generate_thumbnail). Gentle fallback se
file non leggibile.
"""
from __future__ import annotations

from typing import Optional

from app.services.tech_specs_extractor import register_extractor
from app.services.tech_specs_extractor.base import TechSpecsExtractor


@register_extractor(name="pillow", mime_priority=["image/*"])
class PillowExtractor(TechSpecsExtractor):
    def extract(self, path: str, mime: Optional[str] = None) -> dict:
        out = {"tool": "pillow", "container": None, "video": None, "audio": [], "errors": []}
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            out["errors"].append("Pillow non disponibile")
            return out
        try:
            with Image.open(path) as img:
                out["video"] = {
                    "width": img.width,
                    "height": img.height,
                    "codec": (img.format or "").upper(),
                    "pixel_format": img.mode,
                }
                out["container"] = {"format": (img.format or "").lower()}
        except FileNotFoundError:
            out["errors"].append(f"file non trovato: {path}")
        except Exception as e:
            out["errors"].append(f"pillow exception: {type(e).__name__}: {e}")
        return out
