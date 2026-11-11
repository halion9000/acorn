"""What a BEC search leaves behind besides its report: a case and a HaloPSA ticket, both opened when a person starts the search and both written to when it finishes.

A search takes minutes (CIPP says up to ten), so the person should not have to sit watching it. When someone presses Run BEC search, A.C.O.R.N opens a case (``aisoc_cases``) and queues a ``create_ticket`` request for
CORE (the same queue ticket rules use); CORE opens the HaloPSA ticket and reports its number. When the search finishes, the result is written on the case and, as a private note, on the ticket (``ticket_note``).
The ticket number and the finished result can arrive in either order, so each side checks for the other: whichever comes second writes the note, and ``ticket_note_queued`` makes sure it is written once.

Nothing here decides a person is compromised: the note repeats CIPP's own rating and the lists CIPP's score reads (``bec_findings``), and a search that failed says so plainly.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text

from app.models.bec_case import BecCase
from app.models.client_alias import ClientAlias
from app.models.vendor_action import VendorAction
from app.services.bec_findings import LEVEL_SEVERITY, signal_counts

logger = logging.getLogger(__name__)

TICKET_UID_PREFIX = "bec-ticket:"
TITLE_MAX = 200


def ticket_summary(email: str) -> str:
    return f"BEC search: {email}"[:TITLE_MAX]


def start_note(case_ref: str, email: str) -> str:
    return f"A business email compromise search for {email} was started in A.C.O.R.N ({case_ref}). It reads Microsoft 365 through CIPP and changes nothing. The result will be added when it finishes."


def result_text(
    *, case_ref: str, email: str, status: str, message: str | None, summary: dict[str, Any], report: dict[str, Any] | None
) -> str:
    """The plain-language result, for the case and the ticket (pure). A failed search says why; a finished one repeats CIPP's rating and what its lists hold, and never calls a Low rating "clean"."""
    if status != "done":
        why = f" Reason: {message}" if message else ""
        return (
            f"The BEC search {case_ref} for {email} did not finish.{why} No result was produced; start it again from the Identities page."[
                :3000
            ]
        )
    level = str(summary.get("level") or "").strip()
    score = summary.get("score")
    parts = [f"The BEC search {case_ref} for {email} finished."]
    if level:
        has_score = isinstance(score, int | float) and not isinstance(score, bool)
        parts.append(f"CIPP rates it {level}" + (f" (score {score})." if has_score else "."))
    else:
        parts.append("CIPP gave no rating.")
    signals = signal_counts(report)
    if signals:
        parts.append("Seen in the report: " + "; ".join(f"{n} {w}{'' if n == 1 else 's'}" for w, n in signals) + ".")
    else:
        parts.append("None of the lists CIPP's score reads has an entry.")
    raw = summary.get("incomplete")
    incomplete = [x for x in raw if isinstance(x, str)][:12] if isinstance(raw, list) else []
    if incomplete:
        parts.append("These parts could not finish, so the rating is weaker than it reads: " + ", ".join(incomplete) + ".")
    parts.append("The full report is on the person's row on the Identities page.")
    return " ".join(parts)[:3000]


def case_severity(summary: dict[str, Any]) -> str:
    """The case starts at medium (a search was asked for, nothing is known); CIPP's own High or Medium level sets it, a Low or missing one leaves it."""
    return LEVEL_SEVERITY.get(str(summary.get("level") or "").strip().lower(), "medium")


async def halo_client_for(db: Any, owner_id: uuid.UUID, client_id: uuid.UUID) -> str | None:
    row = (
        (
            await db.execute(
                select(ClientAlias.vendor_client_id).where(
                    ClientAlias.tenant_id == owner_id,
                    ClientAlias.vendor == "halopsa",
                    ClientAlias.child_tenant_id == client_id,
                    ClientAlias.ignored.is_(False),
                )
            )
        )
        .scalars()
        .first()
    )
    return str(row) if row else None


async def open_followup(
    db: Any, *, owner_id: uuid.UUID, client_id: uuid.UUID, bec: BecCase, requested_by_name: str | None, now: datetime
) -> None:
    """Open the case and queue the ticket for a search the caller has just added (``db`` is in the client's scope; the caller commits). Never raises: the search matters more than its paperwork."""
    try:
        async with db.begin_nested():
            case_id = uuid.uuid4()
            who = (requested_by_name or "a person").strip()[:200]
            body = f"Started by {who}. {start_note(bec.case_ref, bec.email)}"
            await db.execute(
                text(
                    "INSERT INTO aisoc_cases (id, tenant_id, title, description, severity, status, mitre_techniques, alert_ids, compliance_frameworks, tags, "
                    "opened_at, created_at, updated_at, created_by) VALUES (:id, :t, :title, :description, 'medium', 'new', CAST('[]' AS JSONB), "
                    "CAST(:alert_ids AS UUID[]), CAST(:frameworks AS TEXT[]), CAST(:tags AS JSONB), :now, :now, :now, 'system')"
                ),
                {
                    "id": case_id,
                    "t": client_id,
                    "title": ticket_summary(bec.email),
                    "description": body[:4000],
                    "alert_ids": [],
                    "frameworks": [],
                    "tags": json.dumps({"source": "bec_search", "bec_case_id": str(bec.id), "bec_case_ref": bec.case_ref}),
                    "now": now,
                },
            )
            bec.aisoc_case_id = case_id
            halo = await halo_client_for(db, owner_id, client_id)
            db.add(
                VendorAction(
                    id=uuid.uuid4(),
                    tenant_id=client_id,
                    alert_id=None,
                    vendor="core",
                    incident_uid=f"{TICKET_UID_PREFIX}{bec.id}",
                    action="create_ticket",
                    params={"summary": ticket_summary(bec.email), "details": body[:3000], **({"halo_client_id": halo} if halo else {})},
                    status="pending",
                    created_at=now,
                )
            )
            await db.flush()
    except Exception:  # noqa: BLE001
        logger.warning("bec follow-up (case and ticket) could not be opened for bec=%s", bec.id, exc_info=True)


def _queue_note(db: Any, tenant_id: uuid.UUID, bec_id: uuid.UUID, ticket_id: str, note: str, now: datetime) -> None:
    db.add(
        VendorAction(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            alert_id=None,
            vendor="core",
            incident_uid=f"bec-ticket-note:{bec_id}",
            action="ticket_note",
            params={"ticket_ids": [ticket_id], "note": note},
            status="pending",
            created_at=now,
        )
    )


async def _update_case(db: Any, bec: BecCase, note: str, severity: str, ticket_id: str | None, now: datetime) -> None:
    if bec.aisoc_case_id is None:
        return
    await db.execute(
        text(
            "UPDATE aisoc_cases SET description = left(coalesce(description, '') || chr(10) || chr(10) || :note, 4000), "
            "severity = CASE WHEN CAST(:sev AS TEXT) IN ('high', 'medium') THEN CAST(:sev AS TEXT) ELSE severity END, "
            "tags = tags || CAST(:tags AS JSONB), updated_at = :now WHERE id = :id AND tenant_id = :t"
        ),
        {
            "note": note,
            "sev": severity,
            "tags": json.dumps({"ticket": ticket_id} if ticket_id else {}),
            "now": now,
            "id": bec.aisoc_case_id,
            "t": bec.tenant_id,
        },
    )


async def on_result(db: Any, bec: BecCase, now: datetime) -> None:
    """The search has finished (or failed): write the result on the case, and on the ticket if CORE has already given its number. Never raises."""
    try:
        async with db.begin_nested():
            note = result_text(
                case_ref=bec.case_ref, email=bec.email, status=bec.status, message=bec.message, summary=bec.summary or {}, report=bec.report
            )
            await _update_case(db, bec, note, case_severity(bec.summary or {}), bec.ticket_id, now)
            if bec.ticket_id and not bec.ticket_note_queued:
                _queue_note(db, bec.tenant_id, bec.id, bec.ticket_id, note, now)
                bec.ticket_note_queued = True
            await db.flush()
    except Exception:  # noqa: BLE001
        logger.warning("bec follow-up could not write the result for bec=%s", bec.id, exc_info=True)


async def on_ticket_created(db: Any, tenant_id: uuid.UUID, incident_uid: str, ticket_id: str, now: datetime) -> bool:
    """CORE opened the ticket: remember its number, link it on the case, and if the search has already finished write the result on it now. Returns whether it belonged to a search."""
    if not incident_uid.startswith(TICKET_UID_PREFIX):
        return False
    try:
        bec_id = uuid.UUID(incident_uid[len(TICKET_UID_PREFIX) :])
    except ValueError:
        return False
    bec = (await db.execute(select(BecCase).where(BecCase.id == bec_id, BecCase.tenant_id == tenant_id))).scalars().first()
    if bec is None:
        return False
    bec.ticket_id = ticket_id
    if bec.aisoc_case_id is not None:
        await db.execute(
            text("UPDATE aisoc_cases SET tags = tags || CAST(:tags AS JSONB), updated_at = :now WHERE id = :id AND tenant_id = :t"),
            {"tags": json.dumps({"ticket": ticket_id}), "now": now, "id": bec.aisoc_case_id, "t": tenant_id},
        )
    if bec.status in ("done", "failed") and not bec.ticket_note_queued:
        note = result_text(
            case_ref=bec.case_ref, email=bec.email, status=bec.status, message=bec.message, summary=bec.summary or {}, report=bec.report
        )
        _queue_note(db, tenant_id, bec.id, ticket_id, note, now)
        bec.ticket_note_queued = True
    return True
