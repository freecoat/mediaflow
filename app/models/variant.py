"""Bundle L Stack 1 — Modelli variant + schema version.

VariantSchemaVersion: JSON Schema versionato per validazione DeliveryVariant.
Stack consecutivi possono introdurre v2, v3 con additionalProperties:true che
mantiene back-compat.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
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


class DeliveryVariantCategory(str, enum.Enum):
    t1_technical = "t1_technical"
    t2_documentation = "t2_documentation"
    t3_compilation = "t3_compilation"


class DeliveryVariant(Base):
    __tablename__ = "delivery_variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[DeliveryVariantCategory] = mapped_column(
        SAEnum(DeliveryVariantCategory),
        default=DeliveryVariantCategory.t1_technical,
        server_default="t1_technical",
        index=True,
    )
    schema_version_id: Mapped[int] = mapped_column(ForeignKey("variant_schema_versions.id"))
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Campi promossi per filter/query
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    territory: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)
    has_textless: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", index=True)
    has_subtitles: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    delivery_format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    # Tracciabilità origine
    source_capitolato: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_section: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    suggested_price_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("price_items.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_variant_tenant_code"),)
