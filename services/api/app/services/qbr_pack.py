"""The security and "what we did" sections of a client's quarterly business review pack (roadmap r7-af-31). Pure aggregation over rows already read.

The tickets, hours and satisfaction sections come from the metrics the page already shows; there is NO finance information in the pack (Hal, 2026-11-18). The period is the last ``months`` months.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

SEVERITIES = ("critical", "high", "medium", "low", "info")
FINISHED = ("resolved", "fp", "closed")


def period_start(now: datetime, months: int) -> datetime:
    """The start of the period: ``months`` months of 30 days back from now."""
    return now - timedelta(days=30 * max(1, months))


def _by_severity(rows: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter(str(r.get("severity") or "").lower() for r in rows)
    return {s: c.get(s, 0) for s in SEVERITIES}


def security_section(alerts: list[dict[str, Any]], vulns: list[dict[str, Any]], devices: int, since: datetime) -> dict[str, Any]:
    """What the pack says about security. ``alerts`` rows have ``severity``, ``status`` and ``created_at``; ``vulns`` rows (the open ones now) have ``severity`` and ``exploited``."""
    received = [a for a in alerts if a["created_at"] >= since]
    handled = [a for a in received if str(a.get("status") or "").lower() in FINISHED]
    still_open = [a for a in alerts if str(a.get("status") or "").lower() not in FINISHED]
    return {
        "alerts_received": len(received),
        "alerts_received_by_severity": _by_severity(received),
        "alerts_handled": len(handled),
        "alerts_open_now": len(still_open),
        "alerts_open_now_by_severity": _by_severity(still_open),
        "handled_percent": round(100 * len(handled) / len(received)) if received else None,
        "vulnerabilities_open": len(vulns),
        "vulnerabilities_by_severity": _by_severity(vulns),
        "vulnerabilities_exploited": sum(1 for v in vulns if v.get("exploited")),
        "devices": devices,
    }


def work_section(cases: list[dict[str, Any]], alerts: list[dict[str, Any]], since: datetime) -> dict[str, Any]:
    """What we did in the period: cases opened and closed, and alerts we resolved. ``cases`` rows have ``created_at`` and ``closed_at``; ``alerts`` rows have ``status`` and ``resolved_at``."""
    return {
        "cases_opened": sum(1 for c in cases if c["created_at"] >= since),
        "cases_closed": sum(1 for c in cases if c.get("closed_at") is not None and c["closed_at"] >= since),
        "alerts_resolved": sum(1 for a in alerts if a.get("resolved_at") is not None and a["resolved_at"] >= since),
    }


def highlights(security: dict[str, Any], work: dict[str, Any]) -> list[str]:
    """Plain sentences for the top of the pack, only about what there is to say."""
    out: list[str] = []
    if security["alerts_received"]:
        out.append(f"{security['alerts_received']} alerts came in and {security['alerts_handled']} were handled ({security['handled_percent']}%).")
    else:
        out.append("No alerts came in during the period.")
    crit = security["alerts_open_now_by_severity"]["critical"] + security["alerts_open_now_by_severity"]["high"]
    if crit:
        out.append(f"{crit} critical or high alert{'s are' if crit != 1 else ' is'} still open.")
    if security["vulnerabilities_exploited"]:
        out.append(f"{security['vulnerabilities_exploited']} open vulnerabilit{'ies are' if security['vulnerabilities_exploited'] != 1 else 'y is'} known to be exploited in the wild.")
    if work["cases_closed"]:
        out.append(f"{work['cases_closed']} case{'s' if work['cases_closed'] != 1 else ''} closed.")
    return out
