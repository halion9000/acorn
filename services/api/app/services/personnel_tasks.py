"""Onboarding and offboarding checklists per person (pure).

A checklist is started from the built-in list for its kind; a task already on the person's list (same title) is never added twice, so starting a checklist again only adds what is missing. Progress is how many of a
person's tasks of a kind are done.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

KINDS = ("onboarding", "offboarding")

# Each task and how many days after the checklist is started it falls due (offboarding is tighter: access must go quickly).
TEMPLATES: dict[str, tuple[tuple[str, int], ...]] = {
    "onboarding": (
        ("Create the account and assign the licenses", 1),
        ("Set up multi-factor authentication", 2),
        ("Enroll the laptop in device management and endpoint protection", 3),
        ("Give access to the systems the role needs (and record who approved it)", 3),
        ("Assign the policies to accept (Compliance, Policies, Assign)", 7),
        ("Complete the security awareness training", 14),
        ("Hand over the acceptable use and equipment sign-off", 7),
    ),
    "offboarding": (
        ("Disable the account and end its sessions", 0),
        ("Remove multi-factor methods and reset the password", 0),
        ("Collect the laptop and other equipment", 3),
        ("Remove the person from groups, shared mailboxes and applications", 1),
        ("Hand over the mailbox and files to the manager", 3),
        ("Remove the licenses", 7),
        ("Run an access review for the systems the person used", 14),
    ),
}


def norm(email: str | None) -> str:
    return (email or "").strip().lower()


def tasks_to_start(kind: str, existing_titles: set[str], today: date) -> list[tuple[str, date]]:
    """The tasks of the built-in ``kind`` list the person does not have yet, each with its due day (pure). Unknown kind: nothing."""
    have = {t.strip().lower() for t in existing_titles}
    return [(title, today + timedelta(days=days)) for title, days in TEMPLATES.get(kind, ()) if title.strip().lower() not in have]


@dataclass(frozen=True)
class Task:
    kind: str
    done: bool
    due_on: date | None = None


def progress(tasks: list[Task], kind: str, today: date) -> dict[str, int | bool]:
    """How a checklist stands: tasks, done, open and overdue (an open task past its day). ``started`` is false when the person has no task of that kind."""
    mine = [t for t in tasks if t.kind == kind]
    done = sum(1 for t in mine if t.done)
    overdue = sum(1 for t in mine if not t.done and t.due_on is not None and t.due_on < today)
    return {"started": bool(mine), "total": len(mine), "done": done, "open": len(mine) - done, "overdue": overdue}
