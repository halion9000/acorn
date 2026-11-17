"""Asking CORE to look a person up, for Leafy (the Copilot).

A.C.O.R.N holds no CIPP, Huntress or Intune keys: CORE does. A lookup is a queued request (a ``user_lookup`` vendor action for vendor ``core``, the queue CORE already polls every few seconds); CORE reads the person's
sign-ins, audit events, multi-factor setup, mailbox rules and devices, and answers with a short text and the structured result (``result_data``). Reads only: nothing here, and nothing CORE does for it, changes anything.

What can be asked is fixed: one address, and how many days back (1 to 30). The address is checked here (a plain mailbox address, nothing else) because the text Leafy relays comes from people and from monitored
systems; CORE checks it again. A busy tenant is limited to MAX_PER_HOUR lookups an hour, so a looping model cannot hammer a client's Microsoft 365.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models.vendor_action import VendorAction

ACTION = "user_lookup"
VENDOR = "core"
MAX_PER_HOUR = 40
MIN_DAYS, MAX_DAYS, DEFAULT_DAYS = 1, 30, 30
UPN = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@(?:[A-Za-z0-9-]{1,63}\.)+[A-Za-z]{2,24}$")
OPEN = ("pending", "claimed")


class LookupRefused(Exception):
    """The request cannot be queued; the message says why, in words Leafy can pass on."""


def clean_upn(value: Any) -> str:
    """The address as it will be asked for: trimmed, lower case, and plainly a mailbox address (pure)."""
    upn = str(value or "").strip().lower()
    if not UPN.match(upn):
        raise LookupRefused("Give one e-mail address (for example name@client.com), nothing else.")
    return upn


def clamp_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DAYS
    return max(MIN_DAYS, min(MAX_DAYS, days))


async def queue_user_lookup(
    db: Any, tenant_id: uuid.UUID, user_id: uuid.UUID | None, upn: str, days: int, *, now: datetime | None = None
) -> VendorAction:
    """Queue one lookup for CORE, or return the one already waiting or answered in the last two minutes for the same person and window. The caller commits."""
    now = now or datetime.now(UTC)
    upn = clean_upn(upn)
    days = clamp_days(days)
    recent = (
        await db.execute(
            select(VendorAction)
            .where(
                VendorAction.tenant_id == tenant_id,
                VendorAction.vendor == VENDOR,
                VendorAction.action == ACTION,
                VendorAction.created_at >= now - timedelta(minutes=2),
            )
            .order_by(VendorAction.created_at.desc())
        )
    ).scalars()
    for row in recent:
        if (row.params or {}).get("upn") == upn and (row.params or {}).get("days") == days and row.status != "failed":
            return row
    asked = (
        await db.execute(
            select(func.count())
            .select_from(VendorAction)
            .where(VendorAction.tenant_id == tenant_id, VendorAction.action == ACTION, VendorAction.created_at >= now - timedelta(hours=1))
        )
    ).scalar_one()
    if asked >= MAX_PER_HOUR:
        raise LookupRefused(f"{MAX_PER_HOUR} lookups have already been made in the last hour. Try again later.")
    row = VendorAction(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        alert_id=None,
        vendor=VENDOR,
        incident_uid=f"lookup:{uuid.uuid4().hex[:12]}",
        action=ACTION,
        params={"upn": upn, "days": days},
        status="pending",
        requested_by=user_id,
        created_at=now,
    )
    db.add(row)
    await db.flush()
    return row


def present(row: VendorAction) -> dict[str, Any]:
    """What Leafy is told about a lookup: waiting, failed with CORE's reason, or the answer (pure)."""
    base = {"request_id": str(row.id), "person": (row.params or {}).get("upn"), "days": (row.params or {}).get("days")}
    if row.status in OPEN:
        return {**base, "status": "waiting", "message": "CORE has not answered yet. Ask again in about a minute with the same request_id."}
    if row.status == "failed":
        return {**base, "status": "failed", "message": row.result_message or "CORE could not do the lookup."}
    return {**base, "status": "done", "summary": row.result_message, "result": row.result_data or {}}


async def read_lookup(db: Any, tenant_id: uuid.UUID, request_id: Any) -> VendorAction | None:
    """The lookup with this id in this tenant, or None."""
    try:
        rid = uuid.UUID(str(request_id))
    except ValueError:
        return None
    return (
        await db.execute(
            select(VendorAction).where(VendorAction.id == rid, VendorAction.tenant_id == tenant_id, VendorAction.action == ACTION)
        )
    ).scalar_one_or_none()
