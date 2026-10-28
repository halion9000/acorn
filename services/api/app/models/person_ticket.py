"""One ticket that names a person, as the ticketing tool (HaloPSA) knows it (migration 119)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonTicket(Base):
    __tablename__ = "person_tickets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(String(40), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_email: Mapped[str] = mapped_column(String(320), nullable=False)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
