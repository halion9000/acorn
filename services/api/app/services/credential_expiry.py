"""Reminders for stored credentials that have a known end date (a client secret, a certificate, a token that expires).

The owner types a name and a date; nothing here ever holds the credential itself. They live in the owner tenant's settings (no schema change). A date within ``WARN_DAYS`` is a warning on the platform health page, within ``ERROR_DAYS`` or past is an error.
"""

from __future__ import annotations

from datetime import date
from typing import Any

MAX_ENTRIES = 50
MAX_NAME = 80
WARN_DAYS = 30
ERROR_DAYS = 7


class InvalidEntries(ValueError):
    pass


def clean_entries(raw: Any) -> list[dict[str, str]]:
    """The entries as they are stored: a list of ``{name, expires_on}``, names trimmed and unique (any case), dates ISO ``YYYY-MM-DD``. Raises ``InvalidEntries`` naming what is wrong; nothing is silently dropped."""
    if not isinstance(raw, list):
        raise InvalidEntries("The list of credentials must be a list.")
    if len(raw) > MAX_ENTRIES:
        raise InvalidEntries(f"At most {MAX_ENTRIES} credentials can be tracked.")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise InvalidEntries(f"Entry {i} is not a name and a date.")
        name = " ".join(str(item.get("name", "")).split())
        if not name:
            raise InvalidEntries(f"Entry {i} has no name.")
        if len(name) > MAX_NAME:
            raise InvalidEntries(f"Entry {i}: the name is longer than {MAX_NAME} characters.")
        try:
            day = date.fromisoformat(str(item.get("expires_on", "")).strip())
        except ValueError as exc:
            raise InvalidEntries(f"{name}: the date must be written YYYY-MM-DD.") from exc
        if name.lower() in seen:
            raise InvalidEntries(f"{name} is listed twice.")
        seen.add(name.lower())
        out.append({"name": name, "expires_on": day.isoformat()})
    return out


def stored_entries(settings: Any) -> list[dict[str, str]]:
    """What the tenant's settings hold, ignoring anything malformed rather than failing the page that reads it."""
    raw = settings.get("credential_expiries") if isinstance(settings, dict) else None
    try:
        return clean_entries(raw) if raw else []
    except InvalidEntries:
        return []


def with_days_left(entries: list[dict[str, str]], today: date) -> list[dict[str, Any]]:
    """Each entry with the days left (negative once past), soonest first (pure)."""
    rows = [{**e, "days_left": (date.fromisoformat(e["expires_on"]) - today).days} for e in entries]
    return sorted(rows, key=lambda r: (r["days_left"], r["name"].lower()))


def warning_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The health-page warnings: one per credential that is past or within ``WARN_DAYS`` (pure)."""
    out = []
    for r in rows:
        left = r["days_left"]
        if left > WARN_DAYS:
            continue
        when = "has expired" if left < 0 else "expires today" if left == 0 else f"expires in {left} day{'s' if left != 1 else ''}"
        out.append(
            {
                "key": f"credential_expiry:{r['name'].lower()}",
                "level": "error" if left <= ERROR_DAYS else "warn",
                "text": f"{r['name']} {when} ({r['expires_on']}): replace it before it stops working",
            }
        )
    return out
