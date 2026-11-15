"""The trust center settings (migration 189) and audits with their evidence requests (migration 190)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class TrustCenterSettings(Base):
    __tablename__ = "trust_center_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    headline: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    about: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    frameworks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    policy_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    documents: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    updated_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class Audit(Base):
    __tablename__ = "audits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    framework: Mapped[str] = mapped_column(String(20), nullable=False)
    auditor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="planning")
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class AuditRequest(Base):
    __tablename__ = "audit_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    audit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    control_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
