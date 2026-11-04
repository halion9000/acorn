"""The owner's decision that two addresses are one person ('merge') or are not ('separate'), kept per client (migration 145)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class IdentityMerge(Base):
    __tablename__ = "identity_merges"
    __table_args__ = (CheckConstraint("address_a < address_b", name="identity_merges_sorted"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    address_a: Mapped[str] = mapped_column(String(320), primary_key=True)
    address_b: Mapped[str] = mapped_column(String(320), primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
