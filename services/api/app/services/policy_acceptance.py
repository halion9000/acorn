"""Who has accepted a policy's current version, and who has not (pure).

People are the organization's active people (a licensed, non-guest account that is not disabled). An acceptance counts for the version it names; a newer version asks everyone again, so someone who accepted
only an older version is listed as ``older`` (with the version they accepted) and still counts as pending.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def norm(email: str) -> str:
    return email.strip().lower()


@dataclass(frozen=True)
class Accepted:
    email: str
    name: str | None
    version: int
    accepted_on: date
    recorded_by: str | None = None


def summarize(people: list[tuple[str, str | None]], rows: list[Accepted], version: int) -> dict:
    """Split ``people`` (email, name) by acceptance of ``version``. Also returns acceptances by someone not in ``people`` (``others``: left the company or never listed), and the share accepted."""
    now = {norm(r.email): r for r in rows if r.version == version}
    latest_old: dict[str, Accepted] = {}
    for r in rows:
        if r.version < version and (norm(r.email) not in latest_old or r.version > latest_old[norm(r.email)].version):
            latest_old[norm(r.email)] = r
    listed = {norm(e) for e, _ in people}
    accepted = [now[norm(e)] for e, _ in sorted(people, key=lambda p: norm(p[0])) if norm(e) in now]
    pending = [
        {"email": norm(e), "name": n, "older_version": latest_old[norm(e)].version if norm(e) in latest_old else None}
        for e, n in sorted(people, key=lambda p: norm(p[0]))
        if norm(e) not in now
    ]
    others = [r for k, r in sorted(now.items()) if k not in listed]
    total = len(people)
    return {
        "version": version,
        "accepted": accepted,
        "pending": pending,
        "others": others,
        "share": round(len(accepted) / total, 3) if total else None,
    }
