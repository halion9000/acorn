"""A compliance framework turned on for a tenant (migration 182)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ComplianceEnabledFramework(Base):
    __tablename__ = "compliance_enabled_frameworks"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    framework: Mapped[str] = mapped_column(String(40), primary_key=True)
    enabled_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
