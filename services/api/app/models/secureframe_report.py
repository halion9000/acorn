"""The latest report CORE sent from Secureframe (migration 130)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class SecureframeReport(Base):
    __tablename__ = "secureframe_reports"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class SecureframeHistory(Base):
    """Secureframe's counts for one day (migration 131)."""

    __tablename__ = "secureframe_history"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    passing: Mapped[int] = mapped_column(Integer, nullable=False)
    failing: Mapped[int] = mapped_column(Integer, nullable=False)
    risks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    policies: Mapped[int | None] = mapped_column(Integer, nullable=True)
