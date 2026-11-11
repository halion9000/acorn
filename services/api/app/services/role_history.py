"""A role's recent changes, in plain words, from the audit entries the role endpoints write (role:created, role:updated, role:assigned, role:revoked, role:deleted).

Pure: the entries are read by the endpoint; this only words them. An entry it does not recognise is still shown, with its action name, so nothing is hidden.
"""

from __future__ import annotations

from typing import Any

SHOWN = 10
NAMES_SHOWN = 6


def _names(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list | tuple) else []


def _list(names: list[str]) -> str:
    if len(names) <= NAMES_SHOWN:
        return ", ".join(names)
    return f"{', '.join(names[:NAMES_SHOWN])} and {len(names) - NAMES_SHOWN} more"


def change_sentence(action: str, changes: Any) -> str:
    """One sentence for one audit entry; never raises on an odd or missing payload."""
    data = changes if isinstance(changes, dict) else {}
    if action == "role:created":
        names = _names(data.get("permissions"))
        return f"Created with {_list(names)}." if names else "Created with no permissions."
    if action == "role:updated":
        parts: list[str] = []
        name = data.get("name")
        if isinstance(name, dict) and name.get("before") != name.get("after") and name.get("after"):
            parts.append(f"Renamed from {name.get('before')} to {name.get('after')}.")
        added, removed = _names(data.get("permissions_added")), _names(data.get("permissions_removed"))
        if added:
            parts.append(f"Gained {_list(added)}.")
        if removed:
            parts.append(f"Lost {_list(removed)}.")
        return " ".join(parts) or "Saved with no change."
    if action == "role:assigned":
        return f"Given to user {data.get('user_id')}." if data.get("user_id") else "Given to a user."
    if action == "role:revoked":
        return f"Taken from user {data.get('user_id')}." if data.get("user_id") else "Taken from a user."
    if action == "role:deleted":
        return "Deleted."
    return action


def rows(entries: list[dict[str, Any]], shown: int = SHOWN) -> list[dict[str, str | None]]:
    """The newest `shown` entries as {at, by, action, summary}. `entries` are dicts with created_at (a datetime or text), actor_email, action and changes, newest first."""
    out: list[dict[str, str | None]] = []
    for e in entries[:shown]:
        at = e.get("created_at")
        out.append(
            {
                "at": at.isoformat() if hasattr(at, "isoformat") else (str(at) if at else None),
                "by": e.get("actor_email") or None,
                "action": str(e.get("action", "")),
                "summary": change_sentence(str(e.get("action", "")), e.get("changes")),
            }
        )
    return out


def holders(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Who holds the role now, as {user_id, name, email, since, active}: the one who has held it longest first, then by name. ``found`` are dicts with user_id, username, account_name, email,
    is_active and assigned_at. The name is the first of username, account name and email that is not empty."""
    out: list[dict[str, Any]] = []
    for f in found:
        since = f.get("assigned_at")
        out.append(
            {
                "user_id": str(f.get("user_id")),
                "name": str(f.get("username") or f.get("account_name") or f.get("email") or "Unknown user"),
                "email": f.get("email") or None,
                "since": since.isoformat() if hasattr(since, "isoformat") else (str(since) if since else None),
                "active": f.get("is_active") is not False,
            }
        )
    return sorted(out, key=lambda h: (h["since"] is None, h["since"] or "", h["name"].lower()))
