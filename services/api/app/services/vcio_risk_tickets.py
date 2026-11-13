"""A HaloPSA ticket from a Client Risk Score question.

A person presses "Create a HaloPSA ticket" on a question's line, names the ticket and writes a private note. A.C.O.R.N holds no HaloPSA key, so it does what it does for BEC searches: it queues a
``create_ticket`` action for CORE (``vendor_actions``, vendor ``core``), CORE opens the ticket and reports its number (``on_created``), and the private note is then queued as a ``ticket_note``
action (CORE writes it as a PRIVATE note and moves the ticket to Tech Updated). CORE reads the ticket's status from HaloPSA now and then and reports it (``apply_statuses``); the question's line shows
it ("On Hold", "Waiting on Customer"), so the person sees where the work is without opening HaloPSA.

The ticket belongs to the client the review is for, so it needs that client to be mapped to a HaloPSA client (Client mapping); the organisation's own reviews have none and are refused with a reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.vcio_risk_ticket import VcioRiskTicket
from app.models.vendor_action import VendorAction

UID_PREFIX = "risk-ticket:"
SUMMARY_MAX = 200
NOTE_MAX = 3000
DETAILS_MAX = 3000
# A ticket is looked up again until this long after HaloPSA last called it closed, then left alone (a closed ticket rarely changes, and the list CORE is handed stays short).
CLOSED_WORDS = ("closed", "resolved", "completed", "cancelled", "canceled", "done")
KEEP_LOOKING_AFTER_CLOSED = timedelta(days=2)
# How many tickets CORE is handed to look up in one round.
TRACKED_MAX = 200


def is_closed(status: str | None) -> bool:
    """HaloPSA's status reads as a finished ticket (the same words as the alert page)."""
    word = (status or "").strip().lower()
    return any(word.startswith(w) for w in CLOSED_WORDS)


def clean_summary(value: str) -> str:
    return " ".join(str(value or "").split())[:SUMMARY_MAX]


def ticket_details(question: dict[str, Any], client_name: str, review_date: str, by: str) -> str:
    """The description of the ticket: where it came from, so whoever opens it in HaloPSA knows what it is about."""
    severity = str(question.get("severity") or "").strip()
    lines = [
        f"Raised from the Client Risk Score of {client_name} (review {review_date}) by {by}.",
        "",
        f"Question {question.get('id')}: {question.get('text')}",
        *([f"Severity: {severity}"] if severity else []),
    ]
    return "\n".join(lines)[:DETAILS_MAX]


async def queue_ticket(
    db: Any,
    *,
    halo_client_id: str | None,
    client_id: uuid.UUID,
    client_name: str,
    assessment_id: uuid.UUID,
    review_date: str,
    question: dict[str, Any],
    summary: str,
    private_note: str,
    by: str,
    now: datetime,
) -> VcioRiskTicket:
    """Record the request and queue it for CORE. ``db`` is in the client's scope; the caller commits. ``halo_client_id`` is the HaloPSA client the review's client is mapped to, read by the caller in the
    organisation's scope (the mapping is the organisation's, not the client's). Raises ValueError (a reason safe to show) when there is none."""
    halo = halo_client_id
    if not halo:
        raise ValueError(
            "This client is not linked to a HaloPSA client yet, so CORE would not know where to open the ticket. Link it in Client mapping first."
        )
    row = VcioRiskTicket(
        id=uuid.uuid4(),
        tenant_id=client_id,
        assessment_id=assessment_id,
        question_id=str(question["id"]),
        summary=clean_summary(summary),
        private_note=(private_note or "").strip()[:NOTE_MAX],
        state="waiting",
        created_by=by[:320],
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.add(
        VendorAction(
            id=uuid.uuid4(),
            tenant_id=client_id,
            alert_id=None,
            vendor="core",
            incident_uid=f"{UID_PREFIX}{row.id}",
            action="create_ticket",
            params={
                "summary": row.summary,
                "details": ticket_details(question, client_name, review_date, by),
                "halo_client_id": halo,
                "rule": "risk_score",
            },
            status="pending",
            created_at=now,
        )
    )
    await db.flush()
    return row


def _ticket_id_of(incident_uid: str) -> uuid.UUID | None:
    if not incident_uid.startswith(UID_PREFIX):
        return None
    try:
        return uuid.UUID(incident_uid[len(UID_PREFIX) :])
    except ValueError:
        return None


async def on_created(db: Any, tenant_id: uuid.UUID, incident_uid: str, ticket_id: str, now: datetime) -> bool:
    """CORE opened the ticket: remember its number and queue the private note. Returns whether it belonged to a question."""
    row_id = _ticket_id_of(incident_uid)
    if row_id is None:
        return False
    row = (
        (await db.execute(select(VcioRiskTicket).where(VcioRiskTicket.id == row_id, VcioRiskTicket.tenant_id == tenant_id)))
        .scalars()
        .first()
    )
    if row is None:
        return False
    row.state = "opened"
    row.ticket_id = ticket_id
    row.message = None
    row.updated_at = now
    if row.private_note:
        db.add(
            VendorAction(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                alert_id=None,
                vendor="core",
                incident_uid=f"risk-ticket-note:{row.id}",
                action="ticket_note",
                params={"ticket_ids": [ticket_id], "note": row.private_note},
                status="pending",
                created_at=now,
            )
        )
    return True


async def on_failed(db: Any, tenant_id: uuid.UUID, incident_uid: str, message: str | None, now: datetime) -> bool:
    """CORE could not open the ticket: say why on the line. Returns whether it belonged to a question."""
    row_id = _ticket_id_of(incident_uid)
    if row_id is None:
        return False
    row = (
        (await db.execute(select(VcioRiskTicket).where(VcioRiskTicket.id == row_id, VcioRiskTicket.tenant_id == tenant_id)))
        .scalars()
        .first()
    )
    if row is None:
        return False
    row.state = "failed"
    row.message = (message or "CORE did not say why.")[:1000]
    row.updated_at = now
    return True


async def tracked_ticket_ids(db: Any, tenant_id: uuid.UUID, now: datetime | None = None) -> list[str]:
    """The HaloPSA ticket numbers CORE should read the status of, for one client (``db`` is in its scope): every ticket opened from a question that is not closed, or was closed only recently. At most
    ``TRACKED_MAX``, the oldest check first."""
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(VcioRiskTicket.ticket_id, VcioRiskTicket.status, VcioRiskTicket.status_checked_at)
            .where(VcioRiskTicket.tenant_id == tenant_id, VcioRiskTicket.ticket_id.isnot(None))
            .order_by(VcioRiskTicket.status_checked_at.asc().nullsfirst())
        )
    ).all()
    out: list[str] = []
    for ticket_id, status, checked in rows:
        if is_closed(status) and checked is not None and now - checked > KEEP_LOOKING_AFTER_CLOSED:
            continue
        if ticket_id and ticket_id not in out:
            out.append(ticket_id)
    return out[:TRACKED_MAX]


async def apply_statuses(db: Any, tenant_id: uuid.UUID, statuses: dict[str, str | None], now: datetime) -> int:
    """Record the status CORE read for each ticket number, on every question ticket with that number in this client. A ticket with no status text keeps the last one. Returns how many rows changed."""
    changed = 0
    wanted = [t for t, s in statuses.items() if s]
    if not wanted:
        return 0
    rows = (
        (await db.execute(select(VcioRiskTicket).where(VcioRiskTicket.tenant_id == tenant_id, VcioRiskTicket.ticket_id.in_(wanted))))
        .scalars()
        .all()
    )
    for row in rows:
        new = (statuses.get(row.ticket_id or "") or "").strip()[:100]
        row.status_checked_at = now
        if new and new != row.status:
            row.status = new
            row.updated_at = now
            changed += 1
    return changed
