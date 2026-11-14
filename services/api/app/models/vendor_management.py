"""Vendor management (migration 183): vendors, their security reviews, the documents held for them, and the history of changes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _fk(table: str) -> ForeignKey:
    return ForeignKey(f"{table}.id", ondelete="CASCADE")


class Vendor(Base):
    __tablename__ = "vendors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("tenants"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    trust_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    service: Mapped[str | None] = mapped_column(String(300), nullable=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="Other")
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, default="unassessed")
    data_access: Mapped[str] = mapped_column(String(12), nullable=False, default="unknown")
    auth_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    mfa: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    account_manager_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_manager_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contract_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    review_interval_months: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class VendorReview(Base):
    __tablename__ = "vendor_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("tenants"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("vendors"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="one_time")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="in_progress")
    reviewer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(12), nullable=True)
    findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class VendorDocument(Base):
    __tablename__ = "vendor_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("tenants"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("vendors"), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(40), nullable=False, default="Other")
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    added_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class VendorHistory(Base):
    __tablename__ = "vendor_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("tenants"), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("vendors"), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
