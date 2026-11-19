"""A scheduled report: which report, who gets it, how often (migration 226)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Text

from app.db.database import Base


class ReportSchedule(Base):
    __tablename__ = "report_schedules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    report_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    emails: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    frequency: Mapped[str] = mapped_column(String(8), nullable=False)
    day: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    hour_utc: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
