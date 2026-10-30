"""Alerts raised when a watched tool check gets worse.

The checks CORE sends (Google super admins without 2-Step, leaked credentials on the dark web, a tool's admin sign-in losing its second factor) are a state. An analyst looking at the page sees
today's state, but nobody is told the day a check went from fine to failing. A change of a watched check for the worse becomes one alert in that client's own tenant.

Only a change raises one: the first report of a check (nothing before it to compare with) never does, so connecting a tool for a client does not open a pile of alerts at once.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.models.alert import Alert

RANK = {"met": 0, "partly": 1, "not_met": 2}
CONNECTOR_TYPE = "aisoc-checks"


# key -> (title, severity, the least bad status that raises it). A check that goes from met to "partly" is not always news; for the dark web it is (new findings), for the others only "not_met" is.
WATCHED: dict[str, tuple[str, str, str]] = {
    "threatmate_google_admins": ("Google super administrators without 2-Step Verification", "high", "not_met"),
    "threatmate_google_failed_logins": ("Many failed Google sign-ins for this client", "medium", "not_met"),
    "threatmate_deep_dark_web": ("New deep and dark web findings for this client", "high", "partly"),
    "meraki_admin_2fa": ("Meraki administrators without two-factor sign-in", "high", "not_met"),
    "dnsfilter_org_mfa": ("DNSFilter organization without multi-factor sign-in", "medium", "not_met"),
    "autoelevate_enforcing": ("AutoElevate stopped enforcing for this client", "medium", "not_met"),
    "huntress_protection": ("Huntress protection fell below target for this client", "high", "not_met"),
    "slide_verification": ("A Slide backup failed verification", "medium", "not_met"),
}


def worsened(previous: str | None, status: str, least: str) -> bool:
    """True when ``status`` is worse than ``previous`` (which must exist) and at least as bad as ``least``."""
    if previous not in RANK or status not in RANK:
        return False
    return RANK[status] > RANK[previous] and RANK[status] >= RANK[least]


def alerts_for_changes(changes: list[dict[str, Any]], source: str, now: datetime) -> list[dict[str, Any]]:
    """The alerts a report's changes call for, as plain dicts (``title``, ``severity``, ``description``, ``idempotency_key``, ``key``), one per watched check that got worse. ``changes`` come from
    ``check_history.changes``."""
    out: list[dict[str, Any]] = []
    for c in changes:
        watched = WATCHED.get(c["key"])
        if watched is None or not worsened(c.get("previous_status"), c["status"], watched[2]):
            continue
        title, severity, _least = watched
        evidence = str(c.get("evidence") or "").strip()
        out.append(
            {
                "key": c["key"],
                "title": title,
                "severity": severity,
                "description": f"{evidence} (was {c['previous_status'].replace('_', ' ')}, now {c['status'].replace('_', ' ')})".strip(),
                "idempotency_key": f"check:{source}:{c['key']}:{now.date().isoformat()}:{c['status']}"[:128],
            }
        )
    return out


def build_alert(tenant_id: uuid.UUID, source: str, spec: dict[str, Any], now: datetime) -> Alert:
    """One alert row for a spec from ``alerts_for_changes``."""
    return Alert(
        tenant_id=tenant_id,
        title=spec["title"],
        description=spec["description"],
        severity=spec["severity"],
        status="new",
        priority=80 if spec["severity"] == "high" else 50,
        category="posture",
        connector_type=CONNECTOR_TYPE,
        rule_id=f"check:{spec['key']}",
        rule_name=spec["title"],
        mitre_tactics=[],
        mitre_techniques=[],
        ai_recommendations=[],
        affected_ips=[],
        affected_hosts=[],
        affected_users=[],
        tags=["posture-change", source, spec["key"]],
        raw_event={"source": CONNECTOR_TYPE, "check": spec["key"], "tool": source},
        event_time=now,
        first_seen=now,
        last_seen=now,
        created_at=now,
        updated_at=now,
        idempotency_key=spec["idempotency_key"],
    )


async def raise_alerts(db: Any, tenant_id: uuid.UUID, source: str, changes: list[dict[str, Any]], now: datetime) -> int:
    """Add the alerts a report's changes call for to ``db`` (the caller commits), skipping one that already exists for the same check, day and status. Returns how many were added."""
    specs = alerts_for_changes(changes, source, now)
    added = 0
    for spec in specs:
        exists = (
            await db.execute(
                select(Alert.id).where(Alert.tenant_id == tenant_id, Alert.idempotency_key == spec["idempotency_key"]).limit(1)
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(build_alert(tenant_id, source, spec, now))
            added += 1
    return added


SECUREFRAME_STALE_DAYS = 14
SECUREFRAME_NEW_WINDOW_DAYS = 7


def secureframe_alerts(failing: list[Any], now: datetime, days: int = SECUREFRAME_STALE_DAYS) -> list[dict[str, Any]]:
    """One alert spec per Secureframe test that has been failing for ``days`` days or more (``failing`` are the report's failing tests with ``key``, ``title``, ``owner`` and ``failing_since``).

    Only a test that has just crossed the threshold raises one: failing for ``days`` days or more but less than ``days`` plus ``SECUREFRAME_NEW_WINDOW_DAYS``. A test that has failed for months is a known
    backlog, not news (the first report after this was added found forty of them, up to two years old), and the Compliance page already lists it. The idempotency key is the test and the threshold, with no
    date, so a test raises its alert once however long it keeps failing.
    """
    out: list[dict[str, Any]] = []
    for t in failing:
        since = t.failing_since
        if since is None:
            continue
        if since.tzinfo is None:
            since = since.replace(tzinfo=now.tzinfo)
        age = (now - since).days
        if age < days or age >= days + SECUREFRAME_NEW_WINDOW_DAYS:
            continue
        ident = t.key or t.title
        owner = f" Owner: {t.owner}." if t.owner else " It has no owner."
        out.append(
            {
                "key": f"secureframe_{ident}"[:80],
                "title": f"Secureframe test failing for {age} days: {t.title}"[:500],
                "severity": "medium",
                "description": f"Secureframe has reported this control test failing since {since.date().isoformat()}.{owner}",
                "idempotency_key": f"secureframe:{ident}:{days}d"[:128],
            }
        )
    return out


async def raise_secureframe_alerts(db: Any, tenant_id: uuid.UUID, failing: list[Any], now: datetime) -> int:
    """Add an alert for each test failing for two weeks or more that has none yet (the caller commits). Returns how many were added."""
    added = 0
    for spec in secureframe_alerts(failing, now):
        exists = (
            await db.execute(
                select(Alert.id).where(Alert.tenant_id == tenant_id, Alert.idempotency_key == spec["idempotency_key"]).limit(1)
            )
        ).scalar_one_or_none()
        if exists is None:
            db.add(build_alert(tenant_id, "secureframe", spec, now))
            added += 1
    return added


SCORE_DROP_POINTS = 10
SCORE_DROP_WINDOW_DAYS = 7


def score_drop_spec(
    today: date, scores: list[tuple[date, int | None]], points: int = SCORE_DROP_POINTS, window: int = SCORE_DROP_WINDOW_DAYS
) -> dict[str, Any] | None:
    """An alert spec when the client's score fell by ``points`` or more since the newest score at least ``window`` days old (up to twice that far back), else None.

    ``scores`` are ``(day, score)`` rows including today's. Rows without a score are ignored. One alert per client per ISO week, so a score that stays low does not repeat it daily.
    """
    usable = {d: sc for d, sc in scores if sc is not None}
    if today not in usable:
        return None
    earlier = sorted(d for d in usable if timedelta(days=window) <= today - d <= timedelta(days=2 * window))
    if not earlier:
        return None
    before = usable[earlier[-1]]
    drop = before - usable[today]
    if drop < points:
        return None
    iso = today.isocalendar()
    return {
        "key": "score_drop",
        "title": f"Check score fell {drop} points in {(today - earlier[-1]).days} days (now {usable[today]})",
        "severity": "medium",
        "description": f"This client's check score was {before} on {earlier[-1].isoformat()} and is {usable[today]} on {today.isoformat()}. See Client Posture for the checks that changed.",
        "idempotency_key": f"score-drop:{iso.year}-W{iso.week:02d}",
    }


async def raise_score_drop(db: Any, tenant_id: uuid.UUID, now: datetime) -> int:
    """Add the score-drop alert for this client when today's score warrants one and none exists for this week (the caller commits). Returns 1 or 0."""
    from app.models.signin import ClientScoreHistory

    today = now.date()
    rows = (
        await db.execute(
            select(ClientScoreHistory.day, ClientScoreHistory.score).where(
                ClientScoreHistory.tenant_id == tenant_id, ClientScoreHistory.day >= today - timedelta(days=2 * SCORE_DROP_WINDOW_DAYS)
            )
        )
    ).all()
    spec = score_drop_spec(today, list(rows))
    if spec is None:
        return 0
    exists = (
        await db.execute(select(Alert.id).where(Alert.tenant_id == tenant_id, Alert.idempotency_key == spec["idempotency_key"]).limit(1))
    ).scalar_one_or_none()
    if exists is not None:
        return 0
    db.add(build_alert(tenant_id, "score", spec, now))
    return 1
