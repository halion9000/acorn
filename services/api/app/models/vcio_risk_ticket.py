"""A HaloPSA ticket a person asked for on one question of a risk-scored review (migration 177): its name and private note, its number once CORE opened it, and its status as CORE last read it."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class VcioRiskTicket(Base):
    __tablename__ = "vcio_risk_tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vcio_risk_assessments.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(String(200), nullable=False)
    private_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # waiting: queued for CORE; opened: HaloPSA gave it a number; failed: CORE could not open it (``message`` says why).
    state: Mapped[str] = mapped_column(String(12), nullable=False, default="waiting")
    ticket_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The ticket's status in HaloPSA as CORE last read it ("On Hold", "Waiting on Customer", "Closed"...), and when. None until CORE has read one.
    status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
