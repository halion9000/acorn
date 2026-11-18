"""The risk register (migration 180): risks, the tasks that treat them, and the history of changes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class RiskRegisterItem(Base):
    __tablename__ = "risk_register_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    ref_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="Other")
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    likelihood: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    impact: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    treatment: Mapped[str] = mapped_column(String(10), nullable=False, default="undecided")
    treatment_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    residual_likelihood: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    residual_impact: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # For a risk whose treatment is accept: the day the acceptance ends and must be decided again (migration 202).
    accepted_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RiskRegisterTask(Base):
    __tablename__ = "risk_register_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risk_register_items.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RiskRegisterHistory(Base):
    __tablename__ = "risk_register_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risk_register_items.id", ondelete="CASCADE"), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class RiskRegisterLevel(Base):
    """The levels a risk had from a moment on (migration 216): the heat map for a date is the newest row of each risk on or before it."""

    __tablename__ = "risk_register_levels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("risk_register_items.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    likelihood: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    impact: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    residual_likelihood: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    residual_impact: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
