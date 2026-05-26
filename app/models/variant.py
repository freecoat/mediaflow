"""Bundle L Stack 1 — Modelli variant + schema version.

VariantSchemaVersion: JSON Schema versionato per validazione DeliveryVariant.
Stack consecutivi possono introdurre v2, v3 con additionalProperties:true che
mantiene back-compat.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.models import Base


class VariantSchemaVersion(Base):
    __tablename__ = "variant_schema_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
