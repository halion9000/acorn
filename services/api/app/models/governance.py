"""The review calendar and the policy library (migration 165)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class GovernanceItem(Base):
    __tablename__ = "governance_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    owner: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False)
    next_due: Mapped[date] = mapped_column(Date, nullable=False)
    last_reviewed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GovernanceVersion(Base):
    __tablename__ = "governance_versions"
    __table_args__ = (UniqueConstraint("item_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("governance_items.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    change_note: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class ComplianceNotice(Base):
    """Where the compliance action items are sent each week (migration 215)."""

    __tablename__ = "compliance_notices"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    emails: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    weekly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class ComplianceTestSchedule(Base):
    """Whether the automated control tests are recorded as evidence every night (migration 219)."""

    __tablename__ = "compliance_test_schedule"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    nightly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
