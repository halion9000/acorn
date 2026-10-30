"""The stock held for clients and the history of each item (migration 132)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="stock")
    customer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    serial: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="checked_in")
    site: Mapped[str | None] = mapped_column(String(200), nullable=True)
    person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    part_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    has_charger: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cpu: Mapped[str | None] = mapped_column(String(200), nullable=True)
    memory: Mapped[str | None] = mapped_column(String(60), nullable=True)
    storage: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ninja_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    accounting_treatment: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deployed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    redeployed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    checked_out_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    checked_in_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    ticket_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")
    external_ref: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("inventory_items.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    event: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(320), nullable=True)
    person: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ticket_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
