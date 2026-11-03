"""Remote management and remote access tools found on client devices, and the decisions about them (migration 141)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


# The client id of a rule that is for every client.
ALL_CLIENTS = uuid.UUID(int=0)


class RemoteToolRule(Base):
    """What the managing company decided about a tool. ``client_id`` is ``ALL_CLIENTS`` for every client; a client's own row wins."""

    __tablename__ = "remote_tool_rules"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    tool_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=lambda: ALL_CLIENTS)
    verdict: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str | None] = mapped_column(String(400), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class DeviceRemoteTool(Base):
    """One tool found on one device of a client."""

    __tablename__ = "device_remote_tools"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    hostname_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    tool_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    # Which server this install belongs to, for tools that are installed once per server (ScreenConnect); '' otherwise. Part of the key: one device can hold more than one install of a tool.
    instance_id: Mapped[str] = mapped_column(String(40), primary_key=True, default="")
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    install_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    vendor: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class RemoteToolScan(Base):
    """When a client's devices were last scanned for these tools by one source, and how many devices were looked at."""

    __tablename__ = "remote_tool_scans"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    vendor: Mapped[str] = mapped_column(String(40), primary_key=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    devices_scanned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
