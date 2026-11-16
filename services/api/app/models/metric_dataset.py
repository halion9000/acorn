"""The latest facts CORE sent for one Metrics dataset (migration 196): staff-weekly, ticket-detail, invoice-lines, dialpad-weekly, m365-roles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

DATASET_KEYS = ("staff-weekly", "ticket-detail", "invoice-lines", "dialpad-weekly", "m365-roles")


class MetricDataset(Base):
    __tablename__ = "metric_datasets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
