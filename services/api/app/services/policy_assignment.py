"""Who must accept which policy, by when, and when to remind them (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

DEFAULT_DAYS = 14
REMIND_EVERY_DAYS = 7
OVERDUE_REMIND_EVERY_DAYS = 3
MAX_PER_PASS = 100


def default_due(today: date) -> date:
    return today + timedelta(days=DEFAULT_DAYS)


def state_of(due_on: date, accepted: bool, today: date) -> str:
    """accepted, overdue (past the due day and not accepted) or pending."""
    if accepted:
        return "accepted"
    return "overdue" if due_on < today else "pending"


def reminder_due(last_reminded_at: datetime | None, due_on: date, now: datetime) -> bool:
    """Whether a person who has not accepted is told again now: at once when never told, then every 7 days, every 3 once the due day has passed (pure)."""
    if last_reminded_at is None:
        return True
    gap = OVERDUE_REMIND_EVERY_DAYS if due_on < now.date() else REMIND_EVERY_DAYS
    return now - last_reminded_at >= timedelta(days=gap) - timedelta(hours=2)  # an hourly pass must not slip a day


@dataclass(frozen=True)
class Owed:
    title: str
    due_on: date
    overdue: bool


def reminder_message(name: str | None, owed: list[Owed], link: str) -> tuple[str, str]:
    """(subject, plain-text body) asking one person to accept the policies they owe."""
    n = len(owed)
    any_overdue = any(o.overdue for o in owed)
    subject = f"[A.C.O.R.N] {'Overdue: ' if any_overdue else ''}{n} polic{'y' if n == 1 else 'ies'} to read and accept"
    lines = [f"Hello{' ' + name if name else ''},", "", f"You have {n} polic{'y' if n == 1 else 'ies'} to read and accept:", ""]
    for o in sorted(owed, key=lambda o: (o.due_on, o.title)):
        lines.append(f"- {o.title}: due {o.due_on.isoformat()}{' (overdue)' if o.overdue else ''}")
    lines += [
        "",
        f"Open them here, read each one and press Accept: {link}"
        if link
        else "Open A.C.O.R.N, go to My policies, read each one and press Accept.",
        "",
        "This message is sent by A.C.O.R.N for your organization.",
    ]
    return subject, "\n".join(lines)
