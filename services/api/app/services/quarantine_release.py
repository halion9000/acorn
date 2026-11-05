"""Releasing a quarantined message from A.C.O.R.N: what an alert says about the message, and the link a ticket carries back to it.

A "user asked to release a quarantined message" alert (raised by CORE from Exchange, through CIPP) records the message's quarantine identity and the CIPP customer it belongs to. A person who decides the
message is safe presses Release on the alert; A.C.O.R.N queues a ``release_quarantine`` action for CORE, which asks CIPP (``ExecQuarantineManagement``, type Release, the sender is NEVER added to an
allow list) to release it. Releasing is a decision a person makes each time: nothing releases on its own, a rule that opens a ticket only carries the link.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.alert import Alert
from app.models.vendor_action import VendorAction
from app.services.alert_status import FINISHED_ALERT_STATUSES

ACTION = "release_quarantine"
VENDOR = "core"
UID_PREFIX = "quarantine-release:"
TICKET_NOTE_ACTION = "ticket_note"
CHECK_ACTION = "quarantine_check"
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
        _queue_ticket_note(db, tenant_id, alert.id, tickets, release_note(by, now), now)
    return True


AUTO_CHECK_WINDOW = timedelta(days=3)
AUTO_CHECK_PER_PASS = 50


async def queue_auto_checks(db: Any, now: datetime | None = None) -> int:
    """Ask CORE to look into why the message was held for each new quarantine-release alert, once, as the alert arrives (so the answer is waiting when someone opens it). The caller owns the transaction.

    Only alerts still open and raised in the last three days; never twice for one alert (any earlier check request, whatever became of it, stops another, so a failing read never loops); at most
    ``AUTO_CHECK_PER_PASS`` a pass. Read-only on the Microsoft side: this only queues the look, never a release. Returns how many were queued."""
    from app.db.rls_scope import acting_as_tenant, cross_tenant_reads  # noqa: PLC0415

    now = now or datetime.now(UTC)
    uid = Alert.raw_event["finding"]["uid"].astext
    asked = select(VendorAction.alert_id).where(
        VendorAction.vendor == VENDOR, VendorAction.action == CHECK_ACTION, VendorAction.alert_id.isnot(None)
    )
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(Alert.id, Alert.tenant_id, Alert.raw_event)
                .where(
                    uid.like(f"{UID_PREFIX}%"),
                    Alert.status.notin_(FINISHED_ALERT_STATUSES),
                    Alert.created_at >= now - AUTO_CHECK_WINDOW,
                    Alert.id.notin_(asked),
                )
                .order_by(Alert.created_at.desc())
                .limit(AUTO_CHECK_PER_PASS)
            )
        ).all()
    queued = 0
    for alert_id, tenant_id, raw_event in rows:
        message = quarantine_of(raw_event)
        if message is None:
            continue
        async with acting_as_tenant(db, tenant_id):
            db.add(
                VendorAction(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    alert_id=alert_id,
                    vendor=VENDOR,
                    incident_uid=f"quarantine:{message['identity']}"[:200],
                    action=CHECK_ACTION,
                    params={"client_id": message["client"], "quarantine_identity": message["identity"], "auto": True},
                    status="pending",
                    created_at=now,
                )
            )
            await db.flush()
        queued += 1
    return queued


def check_note(text: str) -> str:
    """The note written on a ticket: what the look into the message found (pure)."""
    return ("A.C.O.R.N looked into why the message was quarantined (read only):\n" + text)[:1500]


async def store_quarantine_check(db: Any, tenant_id: Any, alert_id: Any, text: str, now: datetime) -> bool:
    """Keep what CORE found on the alert, and put it on the alert's HaloPSA tickets as a note (once). Returns whether it was stored. The caller owns the transaction."""
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tenant_id))).scalar_one_or_none()
    if alert is None:
        return False
    enrichment = dict(alert.enrichment_data) if isinstance(alert.enrichment_data, dict) else {}
    record = {"text": text[:1000], "at": now.isoformat(), "ticketed": False}
    tickets = halo_ticket_ids(enrichment)
    if tickets:
        _queue_ticket_note(db, tenant_id, alert.id, tickets, check_note(text), now)
        record["ticketed"] = True
    enrichment["quarantine_check"] = record
    alert.enrichment_data = enrichment  # a new dict, so the JSONB column is seen as changed
    return True


def _queue_ticket_note(db: Any, tenant_id: Any, alert_id: Any, tickets: list[str], note: str, now: datetime) -> None:
    db.add(
        VendorAction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            alert_id=alert_id,
            vendor=VENDOR,
            incident_uid=f"ticket-note:{alert_id}"[:200],
            action=TICKET_NOTE_ACTION,
            params={"ticket_ids": tickets[:20], "note": note},
            status="pending",
            created_at=now,
        )
    )
