"""A summary of failed sign-ins right now, for the people who run the platform: how many, from how many places, and what is locked.

Only what the throttle already keeps (failures inside its window, see ``login_throttle``). Nothing here names an address that was typed: the throttle counts made-up addresses as well as real ones, so listing them would tell
a reader which are real. Client addresses are shown with their last part hidden, enough to see "one place is hammering" without publishing who it is.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

TOP_SHOWN = 5


def mask_client(ip: str | None) -> str:
    """A client address with its last part hidden (``203.0.113.x``, ``2001:db8:1:x``), or ``unknown`` when there was none."""
    if not ip:
        return "unknown"
    if ":" in ip:
        parts = ip.split(":")
        return ":".join(parts[:3]) + ":x"
    parts = ip.split(".")
    return ".".join(parts[:3]) + ".x" if len(parts) == 4 else "unknown"


def abuse_summary(rows: list[Any], per_address: int, per_client: int, window_minutes: int) -> dict[str, Any]:
    """The counts behind the page from the failures in the window: ``rows`` are ``(email_key, client_ip)`` pairs (pure)."""
    by_address: Counter[str] = Counter()
    by_client: Counter[str] = Counter()
    for email, ip in rows:
        by_address[email] += 1
        if ip:
            by_client[ip] += 1
    masked: Counter[str] = Counter()
    for ip, n in by_client.items():
        masked[mask_client(ip)] += n
    return {
        "window_minutes": window_minutes,
        "failures": len(rows),
        "addresses_tried": len(by_address),
        "clients": len(by_client),
        "locked_addresses": sum(1 for n in by_address.values() if n >= per_address),
        "locked_clients": sum(1 for n in by_client.values() if n >= per_client),
        "busiest_clients": [{"client": c, "failures": n} for c, n in masked.most_common(TOP_SHOWN)],
    }
