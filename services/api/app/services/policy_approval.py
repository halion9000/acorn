"""Who may ask for, and who may decide, the approval of a policy version (pure).

Separation of duties: the person asked to approve cannot be the person asking, and only the person named may decide. A version's status is that of its newest request: ``approved``, ``rejected``,
``pending`` (waiting for the approver), or ``none`` when nobody has asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

COMMENT_MAX = 1000


def norm(email: str | None) -> str:
    return (email or "").strip().lower()


def request_problem(requester: str | None, approver: str | None, pending: bool, version_exists: bool) -> str:
    """Why a request for approval cannot be made, or "" when it can."""
    if not version_exists:
        return "That policy has no such version."
    if "@" not in norm(approver):
        return "Name the person who should approve it, by e-mail address."
    if norm(requester) == norm(approver):
        return "The person who asks cannot approve their own request: name someone else."
    if pending:
        return "This version is already waiting for approval."
    return ""


def decision_problem(user_email: str | None, approver: str, decision_now: str, decision: str, comment: str) -> str:
    """Why a decision cannot be recorded, or "" when it can. Only the named approver decides, once; a rejection says why."""
    if decision not in ("approved", "rejected"):
        return "Choose approve or reject."
    if decision_now != "pending":
        return "This request has already been decided."
    if norm(user_email) != norm(approver):
        return "Only the person named as approver can decide."
    if decision == "rejected" and not comment.strip():
        return "Say why it is rejected, so the author knows what to change."
    return ""


@dataclass(frozen=True)
class Approval:
    id: str
    version: int
    approver: str
    requested_by: str
    requested_at: datetime
    decision: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    comment: str = ""


def status_by_version(rows: list[Approval]) -> dict[int, str]:
    """Each version's status from its NEWEST request (pure)."""
    newest: dict[int, Approval] = {}
    for r in rows:
        if r.version not in newest or r.requested_at > newest[r.version].requested_at:
            newest[r.version] = r
    return {v: a.decision for v, a in newest.items()}
