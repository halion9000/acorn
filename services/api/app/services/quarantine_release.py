"""Releasing a quarantined message from A.C.O.R.N: what an alert says about the message, and the link a ticket carries back to it.

A "user asked to release a quarantined message" alert (raised by CORE from Exchange, through CIPP) records the message's quarantine identity and the CIPP customer it belongs to. A person who decides the
message is safe presses Release on the alert; A.C.O.R.N queues a ``release_quarantine`` action for CORE, which asks CIPP (``ExecQuarantineManagement``, type Release, the sender is NEVER added to an
allow list) to release it. Releasing is a decision a person makes each time: nothing releases on its own, a rule that opens a ticket only carries the link.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.models.alert import Alert
from app.models.vendor_action import VendorAction
from app.services.alert_status import FINISHED_ALERT_STATUSES

ACTION = "release_quarantine"
VENDOR = "core"
UID_PREFIX = "quarantine-release:"
TICKET_NOTE_ACTION = "ticket_note"
# Who a release is credited to when Microsoft 365 shows it released and A.C.O.R.N did not do it.
ELSEWHERE = "someone else"


def _context(raw_event: Any) -> dict[str, Any]:
    unmapped = raw_event.get("unmapped") if isinstance(raw_event, dict) else None
    ctx = unmapped.get("context") if isinstance(unmapped, dict) else None
    return ctx if isinstance(ctx, dict) else {}


def _text(value: Any, limit: int = 300) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, str) and value.strip() else ""


def quarantine_of(raw_event: Any) -> dict[str, str] | None:
    """The message a release alert is about, or None when the alert is not one. It needs the alert to be CORE's quarantine-release kind AND to carry both the message's identity and its CIPP customer.

    ``identity`` is Exchange's quarantine identity (opaque), ``client`` the CIPP customer id, ``recipient`` who it was requested for, ``sender`` and ``kind`` (why it was held) for display (pure)."""
    if not isinstance(raw_event, dict):
        return None
    finding = raw_event.get("finding")
    uid = finding.get("uid") if isinstance(finding, dict) else None
    if not (isinstance(uid, str) and uid.startswith(UID_PREFIX)):
        return None
    ctx = _context(raw_event)
    identity, client = _text(ctx.get("quarantine_identity"), 500), _text(ctx.get("cipp_tenant_id"), 100)
    if not identity or not client:
        return None
    return {
        "identity": identity,
        "client": client,
        "recipient": _text(ctx.get("username"), 320),
        "sender": _text(ctx.get("sender"), 320),
        "kind": _text(ctx.get("quarantine_type"), 60),
    }


def release_link(base_url: str, alert_id: Any) -> str | None:
    """The address that opens the alert with the release panel ready, for a ticket to carry. None when the console's public address is not set or is not a plain https address (pure)."""
    base = (base_url or "").strip().rstrip("/")
    if not base.lower().startswith("https://") or any(c.isspace() for c in base):
        return None
    return f"{base}/alerts/{alert_id}?release=1"


def halo_ticket_ids(enrichment: Any) -> list[str]:
    """The HaloPSA ticket numbers linked to an alert (found by CORE or entered by hand, or opened by a ticket rule), each once, in the order they were linked (pure)."""
    out: list[str] = []
    if isinstance(enrichment, dict):
        for key in ("tickets", "manual_tickets"):
            for t in enrichment.get(key) or []:
                if isinstance(t, dict) and str(t.get("system") or "halopsa") == "halopsa":
                    ticket_id = str(t.get("id", "")).strip()
                    if ticket_id and ticket_id not in out:
                        out.append(ticket_id)
    return out


def release_note(by: str, now: datetime) -> str:
    """The sentence written on the tickets (pure)."""
    when = now.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if by == ELSEWHERE:
        return f"The quarantined message was released by {ELSEWHERE} (A.C.O.R.N saw it released in Microsoft 365 at {when}). Nothing more to release."
    return f"The quarantined message was released from A.C.O.R.N by {by} at {when}."


async def note_quarantine_released(
    db: Any, tenant_id: Any, alert_id: Any, now: datetime, by: str = "A.C.O.R.N", resolve_any_open: bool = True
) -> bool:
    """Record that an alert's message is released, once: on the alert (what the page shows and who did it), the alert closed if it is still open, and a note queued for CORE to write on its HaloPSA tickets.

    ``by`` is the person who released it from A.C.O.R.N, or ``ELSEWHERE`` when it was seen released in Microsoft 365. ``resolve_any_open`` False only closes an alert nobody has started on (an analyst's own decision on a
    release done by someone else is left alone). Returns whether anything was recorded (False when it was already recorded, or the alert is not there). The caller owns the transaction."""
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tenant_id))).scalar_one_or_none()
    if alert is None:
        return False
    enrichment = dict(alert.enrichment_data) if isinstance(alert.enrichment_data, dict) else {}
    if enrichment.get("quarantine_release"):
        return False
    enrichment["quarantine_release"] = {"released_at": now.isoformat(), "by": by[:200]}
    alert.enrichment_data = enrichment  # a new dict, so the JSONB column is seen as changed
    if alert.status not in FINISHED_ALERT_STATUSES and (resolve_any_open or alert.status in ("new", "triaging")):
        alert.status = "resolved"
        alert.resolved_at = now
        alert.updated_at = now
    tickets = halo_ticket_ids(enrichment)
    if tickets:
        db.add(
            VendorAction(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                alert_id=alert.id,
                vendor=VENDOR,
                incident_uid=f"ticket-note:{alert.id}"[:200],
                action=TICKET_NOTE_ACTION,
                params={"ticket_ids": tickets[:20], "note": release_note(by, now)},
                status="pending",
                created_at=now,
            )
        )
    return True
