"""Every case is tied to a HaloPSA ticket (``aisoc_cases.ticket_refs``, migration 237).

Three ways a ticket gets on a case:
 - an alert's ticket rule opens a ticket and a case for the alert: when CORE reports the ticket's number it is put on the alert (``link_created_ticket``) and, here, on every case holding that alert;
 - a person links a ticket by number (a ticket opened elsewhere, or by hand);
 - a person asks for a new ticket from the case (``queue_ticket_for_case``): A.C.O.R.N holds no HaloPSA key, so it queues a ``create_ticket`` action for CORE (vendor ``core``, no alert, the case id in the
   action's ``incident_uid``) and CORE's report of the new number comes back to ``on_ticket_created``.

A ticket number is digits only and is linked once per case, however many times it is reported.
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from app.db.rls_scope import acting_as_tenant
from app.models.client_alias import ClientAlias
from app.models.vendor_action import VendorAction

UID_PREFIX = "case-ticket:"
TICKET_NUMBER = re.compile(r"^[0-9]{1,12}$")
TITLE_MAX = 200
DETAILS_MAX = 3000


def clean_ticket_number(value: Any) -> str | None:
    """The ticket number a person typed, if it is one (pure): digits, optionally with a leading ``#``, ``INC``-style prefixes are not HaloPSA numbers and are refused."""
    s = str(value or "").strip().lstrip("#").strip()
    return s if TICKET_NUMBER.match(s) else None


def has_ticket(refs: Any) -> bool:
    """Whether a case's ticket list holds at least one HaloPSA ticket (pure)."""
    return any(isinstance(r, dict) and str(r.get("id", "")).strip() and str(r.get("system") or "halopsa") == "halopsa" for r in (refs if isinstance(refs, list) else []))


def entry(ticket_id: str, by: str, now: datetime) -> dict[str, str]:
    return {"system": "halopsa", "id": ticket_id, "added_by": by[:200], "added_at": now.isoformat()}


async def link_ticket_to_case(db: Any, tenant_id: uuid.UUID, case_id: uuid.UUID, ticket_id: str, by: str, now: datetime) -> bool:
    """Add a ticket to one case. Linking the same number twice changes nothing. Returns whether it was added. The caller owns the transaction."""
    result = await db.execute(
        text(
            "UPDATE aisoc_cases SET ticket_refs = ticket_refs || CAST(:entry AS JSONB), updated_at = :now "
            "WHERE id = :id AND tenant_id = :t AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(ticket_refs) e WHERE e->>'id' = :ticket AND COALESCE(e->>'system', 'halopsa') = 'halopsa')"
        ),
        {"entry": json.dumps([entry(ticket_id, by, now)]), "now": now, "id": case_id, "t": tenant_id, "ticket": ticket_id},
    )
    return bool(result.rowcount)


async def link_ticket_to_cases_of_alert(db: Any, tenant_id: uuid.UUID, alert_id: uuid.UUID, ticket_id: str, by: str, now: datetime) -> int:
    """Add a ticket (just opened or linked for an alert) to every case that holds the alert. Returns how many cases got it. The caller owns the transaction."""
    result = await db.execute(
        text(
            "UPDATE aisoc_cases SET ticket_refs = ticket_refs || CAST(:entry AS JSONB), updated_at = :now "
            "WHERE tenant_id = :t AND CAST(:alert AS UUID) = ANY (alert_ids) "
            "AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(ticket_refs) e WHERE e->>'id' = :ticket AND COALESCE(e->>'system', 'halopsa') = 'halopsa')"
        ),
        {"entry": json.dumps([entry(ticket_id, by, now)]), "now": now, "t": tenant_id, "alert": str(alert_id), "ticket": ticket_id},
    )
    return int(result.rowcount or 0)


def alert_ticket_numbers(enrichment: Any) -> list[str]:
    """The HaloPSA ticket numbers an alert carries (CORE's matches and the ones entered by hand), each once, in order (pure)."""
    out: list[str] = []
    if not isinstance(enrichment, dict):
        return out
    for key in ("manual_tickets", "tickets"):
        for t in enrichment.get(key) or []:
            if isinstance(t, dict) and str(t.get("system") or "halopsa") == "halopsa":
                n = clean_ticket_number(t.get("id"))
                if n and n not in out:
                    out.append(n)
    return out


async def link_tickets_of_alerts(db: Any, tenant_id: uuid.UUID, case_id: uuid.UUID, alerts: list[Any], now: datetime) -> int:
    """A case was just made from these alerts: put the tickets they already have on the case. Returns how many were added. The caller owns the transaction."""
    added = 0
    for alert in alerts:
        for number in alert_ticket_numbers(getattr(alert, "enrichment_data", None)):
            if await link_ticket_to_case(db, tenant_id, case_id, number, "alert", now):
                added += 1
    return added


async def tie_new_case(
    db: Any,
    owner: uuid.UUID,
    case_id: uuid.UUID,
    alert_ids: list[uuid.UUID],
    holders: dict[str, uuid.UUID],
    ticket_id: str | None,
    by: str,
    now: datetime,
) -> int:
    """A case was just made: put on it the tickets its alerts already have and the ticket number the person typed, if any. Returns how many were added. The caller owns the transaction."""
    from app.models.alert import Alert  # noqa: PLC0415

    alerts: list[Any] = []
    for aid in alert_ids:
        tid = holders.get(str(aid), owner)
        async with acting_as_tenant(db, tid) if tid != owner else contextlib.nullcontext():
            alert = (await db.execute(select(Alert).where(Alert.id == aid, Alert.tenant_id == tid))).scalars().first()
        if alert is not None:
            alerts.append(alert)
    added = await link_tickets_of_alerts(db, owner, case_id, alerts, now)
    if ticket_id and await link_ticket_to_case(db, owner, case_id, ticket_id, by, now):
        added += 1
    return added


def ticket_details(title: str, description: str | None, case_number: str | None, by: str) -> tuple[str, str]:
    """The summary and details of a ticket opened from a case (pure)."""
    summary = " ".join((title or "Case").split())[:TITLE_MAX]
    note = f"\n\nOpened from A.C.O.R.N case {case_number} by {by}." if case_number else f"\n\nOpened from an A.C.O.R.N case by {by}."
    return summary, (str(description or title or "").strip()[: DETAILS_MAX - len(note)] + note)


async def _halo_client(db: Any, tenant_id: uuid.UUID) -> str | None:
    row = (
        await db.execute(
            select(ClientAlias.vendor_client_id)
            .where(ClientAlias.child_tenant_id == tenant_id, ClientAlias.vendor == "halopsa", ClientAlias.ignored.is_(False))
            .limit(1)
        )
    ).first()
    return str(row[0]) if row else None


async def queue_ticket_for_case(db: Any, tenant_id: uuid.UUID, case: Any, by: str, requested_by: uuid.UUID | None, now: datetime | None = None) -> bool:
    """Ask CORE to open a HaloPSA ticket for a case. At most one request waits at a time (pressing the button twice makes one ticket). Returns whether a request was queued. The caller owns the transaction."""
    now = now or datetime.now(UTC)
    uid = f"{UID_PREFIX}{case.id}"
    waiting = (
        await db.execute(
            select(VendorAction.id).where(VendorAction.tenant_id == tenant_id, VendorAction.incident_uid == uid, VendorAction.status.in_(("pending", "claimed")))
        )
    ).first()
    if waiting is not None:
        return False
    summary, details = ticket_details(case.title, case.description, getattr(case, "case_number", None), by)
    halo = await _halo_client(db, tenant_id)
    db.add(
        VendorAction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            alert_id=None,
            vendor="core",
            incident_uid=uid,
            action="create_ticket",
            params={"summary": summary, "details": details, "rule": "case", **({"halo_client_id": halo} if halo else {})},
            status="pending",
            requested_by=requested_by,
            created_at=now,
        )
    )
    return True


async def on_ticket_created(db: Any, tenant_id: uuid.UUID, incident_uid: str, ticket_id: str, now: datetime) -> bool:
    """CORE opened the ticket asked for from a case: put its number on the case. Returns whether the action belonged to a case."""
    if not incident_uid.startswith(UID_PREFIX):
        return False
    try:
        case_id = uuid.UUID(incident_uid[len(UID_PREFIX) :])
    except ValueError:
        return False
    await link_ticket_to_case(db, tenant_id, case_id, ticket_id, "ticket opened from the case", now)
    return True
