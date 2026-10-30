"""Who has a second factor, when Microsoft may not say who registered one.

Microsoft's registration report (which methods each person has set up) needs Entra ID P1. Without it CIPP reports nobody as registered, even where security defaults or a conditional access policy
require everyone to. Reading that as "nobody has multi-factor" is wrong. So: when not one person in a client shows a registered method, registration is *unknown*, and a person counts as covered when
something requires a second factor of them (security defaults, conditional access, or the per-user setting). When even one person shows a method, registration is reported and decides, as before.
"""

from __future__ import annotations

from typing import Any


def required_of(u: Any) -> bool:
    """Something makes this person use a second factor: a conditional access policy, security defaults, or the per-user setting.

    A source in ``ENFORCEMENT_UNREPORTED`` says only who enrolled, never what requires it, so for those rows enrolment is the whole answer: an enrolled person counts as covered (see below)."""
    if (getattr(u, "source", None) or "") in ENFORCEMENT_UNREPORTED:
        return True
    return bool(u.ca_enforced or u.security_defaults or (u.per_user or "").lower() in ("enforced", "enabled"))


def registration_known(users: list[Any]) -> bool:
    """True when the client's data shows at least one person with a registered or usable second factor, so the report exists for this client."""
    return any(u.registered or getattr(u, "capable", False) or getattr(u, "methods", None) for u in users)


def has_second_factor(u: Any, known: bool) -> bool:
    """Whether this person has a second factor: what they registered when that is reported, otherwise whether one is required of them."""
    return bool(u.registered or getattr(u, "capable", False)) if known else required_of(u)


# Rows that are not Microsoft's: the people of a client's Google Workspace, read by ThreatMate and stored under its name. Google says plainly who enrolled in 2-Step Verification and whether it is enforced,
# so a Google group is always judged by what it reports, never by the "Microsoft may not say" fallback above, and never mixed into a judgement about Microsoft 365.
GOOGLE_SOURCES: frozenset[str] = frozenset({"threatmate"})
# Microsoft 365 people read by ThreatMate for a client that has no CIPP (Live Oak's own company is one). ThreatMate says who enrolled in 2-factor but not what requires it, so these rows are judged on enrolment alone, and
# only while no CIPP row exists for the client: CIPP is the fuller source and replaces them (see apply_mfa_users).
THREATMATE_MICROSOFT = "threatmate-microsoft"
ENFORCEMENT_UNREPORTED: frozenset[str] = frozenset({THREATMATE_MICROSOFT})
# Sources whose registration is always reported, so they are never judged by the "Microsoft may not say" fallback.
REGISTRATION_REPORTED: frozenset[str] = GOOGLE_SOURCES | ENFORCEMENT_UNREPORTED
DIRECTORY_NAMES = {"threatmate": "Google Workspace"}


def directory_of(u: Any) -> str:
    """The directory a person was read from, as a name: Microsoft 365 unless the row is from a source in GOOGLE_SOURCES."""
    return DIRECTORY_NAMES.get(getattr(u, "source", None) or "", "Microsoft 365")


def microsoft_rows(users: list[Any]) -> list[Any]:
    """Only the Microsoft 365 people (what the Microsoft-specific answers, such as 'is Microsoft 365 in use', must be read from)."""
    return [u for u in users if (getattr(u, "source", None) or "") not in GOOGLE_SOURCES]


def known_by_source(users: list[Any]) -> dict[str, bool]:
    """Whether registration is reported, judged for each source on its own: Microsoft's depends on its report; Google's is always reported."""
    groups: dict[str, list[Any]] = {}
    for u in users:
        groups.setdefault(getattr(u, "source", None) or "", []).append(u)
    return {src: True if src in REGISTRATION_REPORTED else registration_known(rows) for src, rows in groups.items()}


def second_factor(u: Any, known: dict[str, bool]) -> bool:
    """``has_second_factor`` with registration judged for the person's own source."""
    return has_second_factor(u, known.get(getattr(u, "source", None) or "", False))
