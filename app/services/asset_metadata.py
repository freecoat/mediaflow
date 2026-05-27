"""Bundle L Stack 1 — Wrapper legacy per back-compat con dam.py.

Delega al nuovo `tech_specs_extractor` service. Mantiene la firma esistente
per non rompere `/dam/api/assets/{id}/metadata` (Bundle H3).
"""
from __future__ import annotations

from typing import Optional

from app.services.tech_specs_extractor import extract_tech_specs


def extract_asset_metadata(file_path: str, mime_type: Optional[str] = None) -> dict:
    """API legacy: delega a `extract_tech_specs`. Shape compatibile."""
    return extract_tech_specs(file_path, mime_type)
