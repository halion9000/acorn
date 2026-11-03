"""Tools a client deliberately does not use, so their absence is not reported.

Some clients will never run Huntress, ScreenConnect, Addigy or Field Effect (they use something else, or the tool does not apply). Left alone, every one of their computers is listed as "not in Huntress" on the
Devices page, the client page and the roll-ups, its tool checks fail the client's score, and a worsened check raises an alert. Excluding the tool for that client turns all of that off for that client only.

The choice is kept in the client tenant's settings (``tool_exclusions``, a list of tool names), so it needs no schema change. This module is the one place that knows the allowed names and how they are read and
written; the Devices page, the posture checks and the check alerts all ask it.
"""

from __future__ import annotations

from typing import Any

# The tools whose absence is reported as "missing", named as the Devices page names them.
EXCLUDABLE: tuple[str, ...] = ("addigy", "autoelevate", "dnsfilter", "fieldeffect", "huntress", "ninjaone", "screenconnect", "threatmate")


def of_settings(settings: Any) -> frozenset[str]:
    """The tools excluded for a client, from its tenant settings. Anything that is not a known tool name is ignored, so a hand-edited value cannot widen what is excluded."""
    raw = (settings or {}).get("tool_exclusions") if isinstance(settings, dict) else None
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(v for v in raw if isinstance(v, str) and v in EXCLUDABLE)


def normalize(vendors: list[str]) -> list[str]:
    """A request's list as it is stored: unique and sorted. Raises ValueError naming the first name that is not an excludable tool."""
    seen: set[str] = set()
    for v in vendors:
        name = (v or "").strip().lower()
        if name not in EXCLUDABLE:
            raise ValueError(name or "(empty)")
        seen.add(name)
    return sorted(seen)


def with_exclusions(settings: Any, vendors: list[str]) -> dict[str, Any]:
    """A copy of the tenant settings with the exclusions set (removed entirely when the list is empty)."""
    out = dict(settings or {})
    chosen = normalize(vendors)
    if chosen:
        out["tool_exclusions"] = chosen
    else:
        out.pop("tool_exclusions", None)
    return out


def check_is_excluded(source: str, excluded: frozenset[str]) -> bool:
    """Whether a tool check's ``source`` (``huntress``, ``threatmate-google``...) belongs to an excluded tool."""
    if not excluded:
        return False
    from app.services.infra_review import TOOL_CHECK_SOURCES  # noqa: PLC0415

    return TOOL_CHECK_SOURCES.get(source, source) in excluded
