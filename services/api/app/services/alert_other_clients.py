"""The same alert seen at other clients lately: a campaign hitting several clients shows as one thing instead of a row per client.

"The same alert" is the same exact title, raised in the last 24 hours, at a client other than the one the alert belongs to. Only an organization that has clients gets an answer; it names only its own
tenants. It describes and links; it changes nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

WINDOW_HOURS = 24
# The most alerts read to build the answer, and the most clients listed.
ROW_CAP = 2000
CLIENT_CAP = 20


def summarize(rows: list[dict[str, Any]], names: dict[Any, str]) -> dict[str, Any]:
    """``rows``: [{tenant_id, id, created_at, status}] for alerts with the same title at other tenants (pure). One entry per tenant, the one with the newest alert first."""
    by_tenant: dict[Any, dict[str, Any]] = {}
    for r in rows:
        tid = r["tenant_id"]
        entry = by_tenant.setdefault(
            tid, {"client_id": str(tid), "name": names.get(tid) or "Unknown client", "count": 0, "newest_at": None, "newest_alert_id": None}
        )
        entry["count"] += 1
        created = r.get("created_at")
        if isinstance(created, datetime) and (entry["newest_at"] is None or created > entry["newest_at"]):
            entry["newest_at"] = created
            entry["newest_alert_id"] = str(r["id"])
    clients = sorted(
        by_tenant.values(), key=lambda e: (e["newest_at"] is None, -(e["newest_at"].timestamp() if e["newest_at"] else 0), e["name"])
    )
    for e in clients:
        e["newest_at"] = e["newest_at"].isoformat() if e["newest_at"] else None
    return {
        "window_hours": WINDOW_HOURS,
        "total": len(rows),
        "client_count": len(clients),
        "clients": clients[:CLIENT_CAP],
    }


def is_posture_check(raw_event: Any) -> bool:
    """Whether an alert was raised by A.C.O.R.N's own daily posture checks. The same check is run for every client and fails at many of them for ordinary reasons (missing patches, known
    vulnerabilities), so the same title at several clients is expected and says nothing about a campaign."""
    return isinstance(raw_event, dict) and raw_event.get("source") == "aisoc-checks"


def nothing() -> dict[str, Any]:
    """The answer for an organization with no other tenant to look at."""
    return {"window_hours": WINDOW_HOURS, "total": 0, "client_count": 0, "clients": []}
