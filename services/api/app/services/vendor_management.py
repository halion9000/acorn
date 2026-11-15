"""The vendor register's pure rules: when a vendor's next security review is due, what state its reviews are in, and what a change is called in the history. No database here."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

CATEGORIES = (
    "Cloud and hosting",
    "Security tools",
    "Email and collaboration",
    "Productivity software",
    "Finance and payments",
    "HR and payroll",
    "Support and professional services",
    "Hardware and telecom",
    "Other",
)
DOC_TYPES = (
    "SOC 2 report",
    "SOC 3 report",
    "ISO 27001 certificate",
    "Penetration test summary",
    "Security questionnaire",
    "Contract",
    "Data processing agreement",
    "Insurance certificate",
    "Other",
)
RISK_LEVELS = ("unassessed", "low", "medium", "high", "critical")
DUE_SOON_DAYS = 30
# A contract ending within this many days (or already ended) is an action item on the Compliance overview.
CONTRACT_NOTICE_DAYS = 60


def add_months(d: date, months: int) -> date:
    """The same day months later, or the last day of that month when it has no such day (31 Jan plus one month is 28 or 29 Feb)."""
    index = d.month - 1 + months
    year, month = d.year + index // 12, index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def review_state(interval_months: int | None, reviews: list[Any], created: date, today: date) -> dict[str, Any]:
    """Where a vendor's reviews stand. ``reviews`` are its review rows (anything with ``status``, ``due_date`` and ``completed_at``).

    * ``in_progress`` / ``overdue``: a review is open (overdue once its due date has passed). ``next_due`` is that review's due date.
    * with a schedule and none open: ``current`` until the next one is within 30 days, then ``due``, then ``overdue``. The next one is due the interval after the last completed review (or at once for a vendor never reviewed, counted from the day it was added).
    * no schedule and none open: ``none``.
    """
    open_ones = sorted((r for r in reviews if r.status != "complete"), key=lambda r: r.due_date)
    done = sorted((r.completed_at.date() for r in reviews if r.status == "complete" and r.completed_at is not None), reverse=True)
    last = done[0] if done else None
    if open_ones:
        due = open_ones[0].due_date
        return {"state": "overdue" if due < today else "in_progress", "next_due": due, "last_completed": last}
    if interval_months:
        due = add_months(last if last else created, interval_months if last else 0)
        days = (due - today).days
        state = "overdue" if days < 0 else "due" if days <= DUE_SOON_DAYS else "current"
        return {"state": state, "next_due": due, "last_completed": last}
    return {"state": "none", "next_due": None, "last_completed": last}


def describe_changes(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """One plain line for each field that changed, for the history ("Risk level unassessed to high")."""
    labels = {
        "name": "Name",
        "website": "Website",
        "trust_url": "Trust center link",
        "service": "Service provided",
        "category": "Category",
        "owner": "Owner",
        "risk_level": "Risk level",
        "data_access": "Data access",
        "auth_type": "Sign-in type",
        "mfa": "Two-factor sign-in",
        "account_manager_name": "Account manager",
        "account_manager_email": "Account manager email",
        "contract_start": "Contract start",
        "contract_end": "Contract end",
        "review_interval_months": "Review every (months)",
        "notes": "Notes",
    }
    out: list[str] = []
    for key, label in labels.items():
        if before.get(key) == after.get(key):
            continue
        if key == "notes":
            out.append("Notes changed")
        else:

            def show(v: Any) -> str:
                return "none" if v in (None, "") else ("yes" if v is True else "no" if v is False else str(v))

            out.append(f"{label} {show(before.get(key))} to {show(after.get(key))}")
    return out
