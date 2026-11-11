"""A domain's reputation, as far as it can be said honestly from public data: how long it has been registered, when that registration ends, and how its own mail is behaving.

There is no single free reputation score. These are facts a person can weigh; blocklist status is its own check. A registration record that cannot be read is reported as that, not guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

Tone = Literal["good", "warn", "bad", "unknown"]
RDAP_URL = "https://rdap.org/domain/{domain}"


@dataclass(frozen=True)
class Registration:
    registered: datetime | None
    expires: datetime | None


@dataclass(frozen=True)
class Fact:
    label: str
    text: str
    tone: Tone


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_rdap(body: bytes) -> Registration:
    """The registration and expiry dates from an RDAP domain record. Raises ValueError when it is not an RDAP record."""
    try:
        data = json.loads(body)
    except ValueError:
        raise ValueError("The registration record was not understood.") from None
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("The registration record was not understood.")
    found: dict[str, datetime] = {}
    for e in data["events"]:
        if isinstance(e, dict) and (at := _when(e.get("eventDate"))) is not None and isinstance(e.get("eventAction"), str):
            found.setdefault(e["eventAction"].lower(), at)
    return Registration(found.get("registration"), found.get("expiration"))


def _years(days: int) -> str:
    return f"{days // 365} years" if days >= 730 else f"{days // 30} months" if days >= 60 else f"{days} days"


def facts(
    registration: Registration | None,
    problem: str | None,
    policy: str,
    pass_rate: float | None,
    total: int,
    failed: int,
    now: datetime | None = None,
) -> list[Fact]:
    """The reputation facts, most telling first. `registration` is None when it could not be read (and `problem` says why)."""
    moment = now or datetime.now(UTC)
    out: list[Fact] = []
    if registration is None or registration.registered is None:
        out.append(Fact("Registered", problem or "The registration date is not published for this domain.", "unknown"))
    else:
        age = (moment - registration.registered).days
        tone: Tone = "bad" if age < 30 else "warn" if age < 180 else "good"
        note = " Newly registered domains are a common sign of abuse." if age < 30 else ""
        out.append(Fact("Registered", f"{registration.registered.date()} ({_years(age)} ago).{note}", tone))
    if registration is not None and registration.expires is not None:
        left = (registration.expires - moment).days
        if left < 0:
            out.append(Fact("Registration ends", f"Expired on {registration.expires.date()}.", "bad"))
        elif left <= 30:
            out.append(
                Fact(
                    "Registration ends",
                    f"Expires in {left} days ({registration.expires.date()}). If it lapses, someone else can register it and receive its mail.",
                    "warn",
                )
            )
        else:
            out.append(Fact("Registration ends", f"{registration.expires.date()}.", "good"))
    if pass_rate is None or total == 0:
        out.append(Fact("Its own mail", "No mail seen in this period.", "unknown"))
    else:
        tone = "good" if pass_rate >= 98 else "warn" if pass_rate >= 90 else "bad"
        out.append(Fact("Its own mail", f"{pass_rate}% of {total:,} messages pass DMARC; {failed:,} failed.", tone))
    policy_text = {
        "none": ("Monitor only: pretenders are not stopped.", "warn"),
        "quarantine": ("Quarantine: failing mail goes to spam.", "good"),
        "reject": ("Reject: failing mail is refused.", "good"),
    }
    text, ptone = policy_text.get(policy, (f"Unrecognised policy '{policy}'.", "unknown"))
    out.append(Fact("DMARC policy", text, ptone))  # type: ignore[arg-type]
    return out
