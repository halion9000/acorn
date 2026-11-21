"""Device lifecycle (roadmap r7-af-22): how old each computer is and whether its operating system is still supported.

There is no purchase date in any tool, so age is counted from the day A.C.O.R.N FIRST SAW the machine (and says so everywhere it shows it): a machine already there when a tool was connected counts from that day, so
the age is a floor, not the real age. The operating-system line is the more reliable signal: a Windows or macOS version that its maker no longer patches is a replacement or upgrade candidate whatever the age.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

BANDS = ("under_1", "1_to_3", "3_to_5", "over_5")
BAND_LABELS = {"under_1": "Under 1 year", "1_to_3": "1 to 3 years", "3_to_5": "3 to 5 years", "over_5": "Over 5 years"}

# Windows versions whose security updates have ended (client versions; Windows 10 ended 14 October 2025 unless the extended program is bought).
_WIN_ENDED = re.compile(r"windows (xp|vista|7|8|8\.1|10)\b|windows server (2003|2008|2012)", re.IGNORECASE)
_WIN_SUPPORTED = re.compile(r"windows 11|windows server (2016|2019|2022|2025)", re.IGNORECASE)
# Long-term servicing editions of Windows 10 are patched for years after the ordinary editions ended (LTSC 2021 to January 2027, IoT LTSC 2021 to 2032).
_WIN_LONG_TERM = re.compile(r"ltsc|ltsb|iot", re.IGNORECASE)
_MAC_VERSION = re.compile(r"(?:mac ?os(?: x)?|os x)[^0-9]*(\d{1,2})(?:\.(\d+))?", re.IGNORECASE)


def age_band(first_seen: datetime, now: datetime) -> str:
    """The age band of a machine from the day it was first seen (pure)."""
    years = (now - first_seen).days / 365.25
    return "under_1" if years < 1 else "1_to_3" if years < 3 else "3_to_5" if years < 5 else "over_5"


def os_support(os_name: str | None, os_version: str | None = None) -> str:
    """``ended`` (the maker no longer patches it), ``supported`` or ``unknown`` (pure). Windows by version name; macOS 13 and older ended (macOS 10.x counts as old); Linux and everything else is unknown rather than guessed."""
    text = " ".join(x for x in (os_name, os_version) if x)
    if not text.strip():
        return "unknown"
    if _WIN_ENDED.search(text):
        return "supported" if re.search(r"windows 10", text, re.IGNORECASE) and _WIN_LONG_TERM.search(text) else "ended"
    if _WIN_SUPPORTED.search(text):
        return "supported"
    m = _MAC_VERSION.search(text)
    if m and re.search(r"mac", text, re.IGNORECASE):
        major = int(m.group(1))
        if major == 10:
            return "ended"
        return "ended" if major <= 13 else "supported"
    return "unknown"


def lifecycle_row(d: Any, now: datetime | None = None) -> dict[str, Any]:
    """One computer's lifecycle line (pure over an object with the device fields)."""
    when = now or datetime.now(UTC)
    first = d.first_seen if d.first_seen.tzinfo else d.first_seen.replace(tzinfo=UTC)
    support = os_support(d.os, d.os_version)
    return {
        "device_id": str(d.id),
        "client_name": d.client_name,
        "hostname": d.hostname,
        "os": " ".join(x for x in (d.os, d.os_version) if x) or None,
        "manufacturer": d.manufacturer,
        "model": d.model,
        "serial_number": d.serial_number,
        "first_seen": first.isoformat(),
        "age_days": max(0, (when - first).days),
        "band": age_band(first, when),
        "os_support": support,
        "review": support == "ended" or age_band(first, when) == "over_5",
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The counts above the table (pure): machines per age band, how many run an operating system that ended, and how many are worth a replacement review."""
    return {
        "computers": len(rows),
        "bands": {b: sum(1 for r in rows if r["band"] == b) for b in BANDS},
        "os_ended": sum(1 for r in rows if r["os_support"] == "ended"),
        "os_unknown": sum(1 for r in rows if r["os_support"] == "unknown"),
        "review": sum(1 for r in rows if r["review"]),
    }


def order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Worst first (pure): an ended operating system, then the oldest, then by client and name."""
    return sorted(rows, key=lambda r: (r["os_support"] != "ended", -int(r["age_days"]), r["client_name"] or "", r["hostname"].lower()))
