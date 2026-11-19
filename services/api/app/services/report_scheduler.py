"""Scheduled reports (roadmap r7-af-32, Hal 2026-11-18: "a report scheduler system: for any report choose who gets it, how often, etc.").

A schedule names a report kind (``KINDS``), recipients, a frequency (daily; weekly on a weekday; monthly on day 1 to 28) and an hour (UTC). ``due`` says whether one is due now (pure): it has not run since its
latest slot. ``render`` works the report out as plain text for the e-mail body (the mailer sends text only), for the schedule's own organization or client. Kinds are added by writing one renderer and listing it
here. Sending needs the mail credentials; a report with nothing to say is not sent (a note says so), except when its kind always has something.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.trust_audit import Audit, AuditRequest

MAX_EMAILS = 20
FREQUENCIES = ("daily", "weekly", "monthly")

Renderer = Callable[[Any, uuid.UUID, datetime], Awaitable[tuple[str, str] | None]]


def slot_before(frequency: str, day: int, hour: int, now: datetime) -> datetime:
    """The most recent moment at or before ``now`` this schedule was due to run (pure)."""
    now = now.astimezone(UTC)
    at = now.replace(minute=0, second=0, microsecond=0)
    if frequency == "daily":
        slot = at.replace(hour=hour)
        return slot if slot <= now else slot - timedelta(days=1)
    if frequency == "weekly":
        slot = (at - timedelta(days=(at.weekday() - day) % 7)).replace(hour=hour)
        return slot if slot <= now else slot - timedelta(days=7)
    slot = at.replace(day=min(max(day, 1), 28), hour=hour)
    if slot <= now:
        return slot
    month_before = (at.replace(day=1) - timedelta(days=1)).replace(day=min(max(day, 1), 28), hour=hour)
    return month_before


def due(frequency: str, day: int, hour: int, last_run_at: datetime | None, now: datetime) -> bool:
    """True when the latest slot has passed with no run since it (pure). A schedule never run is due at its first slot after it was made, which the caller sets as ``last_run_at`` on creation."""
    if last_run_at is None:
        return True
    return last_run_at.astimezone(UTC) < slot_before(frequency, day, hour, now)


def clean_emails(raw: list[str]) -> list[str]:
    """The addresses, trimmed, lower case, de-duplicated, at most 20, each with one @ and a dot after it (pure)."""
    out: list[str] = []
    for a in raw:
        a = (a or "").strip().lower()
        if a and a.count("@") == 1 and "." in a.split("@")[1] and " " not in a and a not in out:
            out.append(a)
    return out[:MAX_EMAILS]


async def _compliance_actions(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    from app.api.v1.endpoints.compliance_dashboard import build_dashboard  # noqa: PLC0415 - that module is large
    from app.services import compliance_notice as cn  # noqa: PLC0415

    board = await build_dashboard(db, tenant)
    items = [i.model_dump() for i in board.action_items]
    if not items:
        return None
    subject, text, _payload = cn.digest(items, now, "", "")
    return subject, text


async def _open_audit_requests(db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    audits = {a.id: a for a in (await db.execute(select(Audit).where(Audit.tenant_id == tenant, Audit.status != "complete"))).scalars()}
    if not audits:
        return None
    lines = []
    today = now.date()
    for r in (await db.execute(select(AuditRequest).where(AuditRequest.tenant_id == tenant, AuditRequest.status == "open"))).scalars():
        a = audits.get(r.audit_id)
        if a is None:
            continue
        late = " (overdue)" if r.due_date is not None and r.due_date < today else ""
        lines.append((a.name, r.due_date or date.max, f"- {a.name}: {r.title}{', due ' + r.due_date.isoformat() if r.due_date else ''}{late}"))
    if not lines:
        return None
    lines.sort(key=lambda x: (x[0], x[1]))
    return f"Open audit requests: {len(lines)}", "\n".join([f"{len(lines)} audit request{'s' if len(lines) != 1 else ''} still open:"] + [x[2] for x in lines[:200]])


KINDS: dict[str, tuple[str, Renderer]] = {
    "compliance_actions": ("Compliance action items (what needs doing now)", _compliance_actions),
    "open_audit_requests": ("Open audit requests with due dates", _open_audit_requests),
}


async def render(kind: str, db: Any, tenant: uuid.UUID, now: datetime) -> tuple[str, str] | None:
    """The subject and text of a report, or None when it has nothing to say. Raises KeyError for an unknown kind."""
    return await KINDS[kind][1](db, tenant, now)
