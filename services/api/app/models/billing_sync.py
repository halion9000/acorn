"""Billing sync state per client and invoice line (migration 195): hidden from the list, and the last push to HaloPSA."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BillingSyncItem(Base):
    __tablename__ = "billing_sync_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    invoice_item: Mapped[str] = mapped_column(String, primary_key=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    pushed_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pushed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
