"""Uploaded Nessus scans and their findings, kept per client (migration 137)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class NessusScan(Base):
    __tablename__ = "nessus_scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    scan_type: Mapped[str] = mapped_column(String(8), default="other", nullable=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    hosts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_hosts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    high: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    medium: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    low: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class NessusFinding(Base):
    __tablename__ = "nessus_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("nessus_scans.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    host_name: Mapped[str] = mapped_column(String(255), nullable=False)
    host_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    host_fqdn: Mapped[str | None] = mapped_column(String(255), nullable=True)
    host_os: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    plugin_id: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    severity: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    service: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    cvss: Mapped[float | None] = mapped_column(Float, nullable=True)
    cves: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    exploit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synopsis: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    solution: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
