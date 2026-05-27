"""Bundle L Stack 1 — JSON Schema loader + validator per DeliveryVariant.

Carica lo schema attivo da VariantSchemaVersion (tabella). Valida instance
contro jsonschema. Stack consecutivi possono caricare schema-version diversi
per variant legacy (es. v2 per nuove variant, v1 per quelle vecchie).
"""
from __future__ import annotations

from typing import Optional

from jsonschema import validate
from sqlalchemy.orm import Session

from app.models.variant import VariantSchemaVersion


def load_active_schema(db: Session) -> dict:
    """Ritorna lo schema_json del singolo VariantSchemaVersion con is_active=True.

    Raises:
        RuntimeError se nessuno schema attivo è presente in DB.
    """
    sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.is_active == True).first()  # noqa: E712
    if not sv:
        raise RuntimeError("Nessuno VariantSchemaVersion attivo. Eseguire seed.")
    return sv.schema_json


def load_schema_by_version(db: Session, version: str) -> Optional[dict]:
    """Ritorna schema_json per versione specifica, None se non esiste."""
    sv = db.query(VariantSchemaVersion).filter(VariantSchemaVersion.version == version).first()
    return sv.schema_json if sv else None


def validate_variant_spec(db: Session, spec: dict, schema_version: Optional[str] = None) -> None:
    """Valida `spec` (dict) contro schema attivo (default) o specifica versione.

    Raises:
        jsonschema.exceptions.ValidationError se invalido.
        RuntimeError se schema non trovato.
    """
    if schema_version:
        schema = load_schema_by_version(db, schema_version)
        if schema is None:
            raise RuntimeError(f"VariantSchemaVersion '{schema_version}' non trovata")
    else:
        schema = load_active_schema(db)
    validate(instance=spec, schema=schema)
