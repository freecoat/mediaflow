"""
Branding aziendale (v3.5.0-alpha.66.13).

Helper centralizzato per ottenere le info di branding del tenant da usare
nei PDF (quote / cost report cliente / invoice). Single source of truth.

Pattern d'uso nei PDF:
    from app.services.branding import get_branding
    branding = get_branding(db)  # tenant_id=1 default
    # branding = {
    #   "name", "tagline", "address", "vat_number", "email", "phone", "website",
    #   "logo_path" (Path absolute), "brand_color" (hex), "show_powered_by",
    #   "document_header", "info_html" (HTML pre-formattato per header PDF)
    # }
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session

DEFAULT_BRAND_COLOR = "#D85A30"  # Claqo-red (brand brief v0.1)


def get_branding(db: Session, tenant_id: int = 1) -> dict:
    """Restituisce dict di branding per il tenant. Robusto a tenant=None."""
    from app.models import Tenant
    t = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not t:
        return _default_branding()

    logo_abs = _resolve_logo_path(getattr(t, "logo_path", None))

    info_lines = []
    if t.address:
        info_lines.append(t.address.replace("\n", " · "))
    fiscal_bits = []
    if t.vat_number:
        fiscal_bits.append(f"P.IVA {t.vat_number}")
    if getattr(t, "tax_code", None) and t.tax_code != t.vat_number:
        fiscal_bits.append(f"C.F. {t.tax_code}")
    if fiscal_bits:
        info_lines.append(" — ".join(fiscal_bits))
    contact_bits = []
    if t.email:
        contact_bits.append(t.email)
    if t.phone:
        contact_bits.append(t.phone)
    if t.website:
        contact_bits.append(t.website)
    if contact_bits:
        info_lines.append(" · ".join(contact_bits))

    return {
        "name": t.legal_name or t.name or "Claqo",
        "short_name": t.name or "Claqo",
        "tagline": getattr(t, "tagline", None) or "",
        "address": t.address or "",
        "vat_number": t.vat_number or "",
        "tax_code": getattr(t, "tax_code", None) or "",
        "email": t.email or "",
        "phone": t.phone or "",
        "website": t.website or "",
        "logo_path": logo_abs,  # Path o None
        "brand_color": getattr(t, "brand_color", None) or DEFAULT_BRAND_COLOR,
        "show_powered_by": bool(getattr(t, "show_powered_by", True)),
        "document_header": getattr(t, "document_header", None) or "",
        "info": "\n".join(info_lines),
        "info_html": "<br/>".join(info_lines),
    }


def _default_branding() -> dict:
    return {
        "name": "Claqo",
        "short_name": "Claqo",
        "tagline": "",
        "address": "", "vat_number": "", "tax_code": "",
        "email": "", "phone": "", "website": "",
        "logo_path": None,
        "brand_color": DEFAULT_BRAND_COLOR,
        "show_powered_by": True,
        "document_header": "",
        "info": "", "info_html": "",
    }


def _resolve_logo_path(raw: Optional[str]) -> Optional[Path]:
    """Risolve il logo_path su file system. Restituisce Path absolute o None."""
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        # Relativa al CWD del processo (uploads/tenant/logo.* tipicamente)
        p = Path.cwd() / p
    if p.exists() and p.is_file() and p.stat().st_size < 5_000_000:
        return p
    return None
