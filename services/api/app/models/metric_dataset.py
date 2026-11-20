"""The latest facts CORE sent for one Metrics dataset (migration 196): staff-weekly, ticket-detail, invoice-lines, dialpad-weekly, m365-roles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

DATASET_KEYS = ("staff-weekly", "ticket-detail", "invoice-lines", "dialpad-weekly", "m365-roles", "meetings-weekly")

# Datasets whose sends ADD to what is held instead of replacing it: the list that holds the rows, the fields that identify one row (a newer row replaces the older one with the same identity) and how many
# rows are kept at most (the newest by the first field). CORE sends only the recent weeks it computed, so the history builds up here; Microsoft 365 roles arrive a few clients at a time.
MERGED: dict[str, tuple[str, tuple[str, ...], int]] = {
    "staff-weekly": ("rows", ("week", "agent_id"), 20000),
    "dialpad-weekly": ("rows", ("week", "engineer"), 20000),
    "meetings-weekly": ("rows", ("week", "engineer"), 20000),
    "m365-roles": ("clients", ("client_id",), 5000),
}


def merge_dataset(key: str, held: dict[str, Any] | None, new: dict[str, Any]) -> dict[str, Any]:
    """The dataset to store for ``key``: ``new`` alone for a replaced dataset, else ``new`` with the older rows of ``held`` that ``new`` does not carry again (pure)."""
    rule = MERGED.get(key)
    if rule is None or not held:
        return new
    field, ident, cap = rule
    mine = {tuple(str(r.get(f) or "") for f in ident): r for r in new.get(field) or [] if isinstance(r, dict)}
    kept = [r for r in held.get(field) or [] if isinstance(r, dict) and tuple(str(r.get(f) or "") for f in ident) not in mine]
    older = {tuple(str(r.get(f) or "") for f in ident): r for r in held.get(field) or [] if isinstance(r, dict)}
    # a row sent again replaces the one held, but a field the new row leaves out (ticket updates for a week CORE did not read this time) keeps what was held
    fresh = [{**older.get(k, {}), **r} for k, r in mine.items()]
    rows = sorted([*kept, *fresh], key=lambda r: str(r.get(ident[0]) or ""))[-cap:]
    out = {**held, **new, field: rows}
    if "weeks" in out:
        out["weeks"] = sorted({str(r.get("week")) for r in rows if r.get("week")})
    return out


class MetricDataset(Base):
    __tablename__ = "metric_datasets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
