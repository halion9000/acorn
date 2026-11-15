"""The pure rules of an access review: who is on the list when it starts, what is worth a second look about each person, and when it may be completed. No database here."""

from __future__ import annotations

from typing import Any

STALE_DAYS = 90
MAX_ENTRIES = 3000


def entries_from_mfa_users(users: list[Any]) -> list[dict[str, Any]]:
    """The Microsoft 365 people (rows of ``identity_mfa_users``) as review lines, the ones worth a look first. A flag says why: an administrator, no second sign-in step, a guest, a disabled account that still exists, or
    nobody has signed in for three months."""
    out: list[dict[str, Any]] = []
    for u in users:
        flags: list[str] = []
        if getattr(u, "admin", False):
            flags.append("administrator")
        if getattr(u, "enabled", True) is False:
            flags.append("disabled account")
        if (getattr(u, "user_type", None) or "").lower() == "guest":
            flags.append("guest")
        if getattr(u, "enabled", True) and not getattr(u, "registered", False):
            flags.append("no multi-factor")
        days = getattr(u, "days_since_signin", None)
        if isinstance(days, int) and days > STALE_DAYS:
            flags.append(f"no sign-in for {days} days")
        parts = ["Microsoft 365"]
        parts.append("administrator" if getattr(u, "admin", False) else "member")
        if getattr(u, "licensed", False):
            parts.append("licensed")
        out.append({"person": u.upn, "name": getattr(u, "display_name", None), "access": ", ".join(parts), "flags": flags})
    return _order(out)


def entries_from_identities(rows: list[Any], system: str) -> list[dict[str, Any]]:
    """Another tool's people (rows of ``identity_sources``) as review lines."""
    out: list[dict[str, Any]] = []
    for r in rows:
        flags: list[str] = []
        if getattr(r, "enabled", None) is False:
            flags.append("disabled account")
        if getattr(r, "kind", "user") == "guest":
            flags.append("guest")
        if getattr(r, "kind", "user") == "shared":
            flags.append("shared account")
        out.append(
            {
                "person": r.email,
                "name": getattr(r, "display_name", None),
                "access": f"{system}: {getattr(r, 'kind', 'user')}",
                "flags": flags,
            }
        )
    return _order(out)


def entries_from_names(names: list[str], system: str) -> list[dict[str, Any]]:
    """People typed in for a system with no connected source: one per line, blanks and repeats dropped, in the order given."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for raw in names:
        n = raw.strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append({"person": n[:320], "name": None, "access": system, "flags": []})
    return out


def _order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Most flags first, then by name, so the people who need a decision most are at the top."""
    return sorted(rows, key=lambda r: (-len(r["flags"]), r["person"].lower()))[:MAX_ENTRIES]


def can_complete(decisions: list[str]) -> tuple[bool, int]:
    """Whether a review may be completed (every person decided) and how many are still pending."""
    pending = sum(1 for d in decisions if d == "pending")
    return pending == 0 and len(decisions) > 0, pending


def summarize(decisions: list[str]) -> str:
    """The sentence kept with a completed review."""
    keep, remove = decisions.count("keep"), decisions.count("remove")
    return f"{len(decisions)} people reviewed: {keep} keep their access, {remove} to have it removed."
