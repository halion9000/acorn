"""Automatic playbooks, first version: ALERT AND DRY RUN. Nothing is run.

For each client the MSSP has ticked "Automated playbooks" for (the MSSP dashboard column), this watches that client's recent unresolved alerts, matches each against the playbooks' own
triggers (the shared library of shipped playbooks plus the client's own), and RECORDS "this playbook would have run for this alert, and these are the steps it would have taken"
(``playbook_dry_runs``). People review those on the alert and on the Playbooks page. A playbook is moved to real automation later, one at a time, after its dry runs have been checked.

How a trigger matches an alert (a trigger is ``{"on": "alert", "severity": [...], "tags": [...]}``):
  * the alert's severity is one of the trigger's severities (when it lists any), AND
  * at least one of the trigger's tags is among the alert's signals: its own tags, its category, and ``mitre.t####`` for each technique it names.
A trigger with no tags matches nothing: a playbook for "every high alert" is far too broad to say "would have run" about.

Idempotent: one row per alert per playbook, so the watcher can run as often as it likes.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

LOG = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)  # alerts older than this are not looked at
MAX_ALERTS_PER_TENANT = 500
MAX_STEPS = 30
FINISHED = ("resolved", "closed", "false_positive", "fp", "suppressed")

FetchPlaybooks = Callable[[uuid.UUID], Awaitable[list[dict[str, Any]]]]


def alert_signals(tags: Any, category: Any, techniques: Any) -> set[str]:
    """What an alert says about itself, in the words playbook triggers use: its tags, its category, and ``mitre.t####`` for each technique."""
    out: set[str] = set()
    for t in tags if isinstance(tags, list) else []:
        if isinstance(t, str) and t.strip():
            out.add(t.strip().lower())
    if isinstance(category, str) and category.strip():
        out.add(category.strip().lower())
    for t in techniques if isinstance(techniques, list) else []:
        if isinstance(t, str) and t.strip():
            out.add(f"mitre.{t.strip().lower().split('.')[0]}")
            out.add(f"mitre.{t.strip().lower()}")
    return out


def trigger_matches(trigger: Any, severity: str | None, signals: set[str]) -> list[str] | None:
    """Why the trigger matches (a list of short reasons), or None when it does not."""
    if not isinstance(trigger, dict) or trigger.get("on") not in (None, "alert"):
        return None
    raw_sev = trigger.get("severity")
    severities = (
        [str(s).lower() for s in raw_sev] if isinstance(raw_sev, list) else ([str(raw_sev).lower()] if isinstance(raw_sev, str) else [])
    )
    if severities and (severity or "").lower() not in severities:
        return None
    tags = [str(t).lower() for t in trigger.get("tags") or [] if isinstance(t, str) and t.strip()]
    hits = [t for t in tags if t in signals]
    if not hits:
        return None
    return ([f"severity {severity}"] if severities else []) + [f"tag {t}" for t in hits]


def steps_of(playbook: dict[str, Any]) -> list[dict[str, str]]:
    """What the playbook would do, in order: each step's id, type and name."""
    out = []
    for s in (playbook.get("steps") or [])[:MAX_STEPS]:
        if isinstance(s, dict):
            out.append(
                {
                    "id": str(s.get("id") or ""),
                    "type": str(s.get("type") or "step"),
                    "name": str(s.get("name") or s.get("label") or "")[:120],
                }
            )
    return out


def would_run(playbooks: list[dict[str, Any]], severity: str | None, signals: set[str]) -> list[tuple[dict[str, Any], list[str]]]:
    """The enabled playbooks whose trigger matches, each with the reasons."""
    out = []
    for pb in playbooks:
        if not isinstance(pb, dict) or pb.get("enabled") is False or not pb.get("id"):
            continue
        reasons = trigger_matches(pb.get("trigger"), severity, signals)
        if reasons:
            out.append((pb, reasons))
    return out


async def default_fetch(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """The shared library plus the client's own playbooks, from the agents service."""
    from app.api.v1.endpoints.playbooks import _proxy  # noqa: PLC0415

    body = await _proxy("GET", "", params={"enabled_only": True, "tenant_id": str(tenant_id)})
    return body if isinstance(body, list) else []


async def flagged_tenants(session: Any) -> list[uuid.UUID]:
    """The clients the MSSP allows automated playbooks for."""
    from sqlalchemy import text  # noqa: PLC0415

    rows = (
        await session.execute(text("select id from tenants where settings ->> 'playbook_automation' = 'true' order by created_at, id"))
    ).all()
    return [r[0] for r in rows]


async def record_for_tenant(session: Any, tenant_id: uuid.UUID, playbooks: list[dict[str, Any]], now: datetime) -> int:
    """Record the dry runs missing for one client's recent alerts. The caller owns the transaction (and the tenant scope) and commits. Returns how many were added."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.models.alert import Alert  # noqa: PLC0415
    from app.models.playbook_dry_run import PlaybookDryRun  # noqa: PLC0415

    alerts = (
        (
            await session.execute(
                select(Alert)
                .where(Alert.tenant_id == tenant_id, Alert.created_at >= now - WINDOW, Alert.status.notin_(FINISHED))
                .order_by(Alert.created_at.desc())
                .limit(MAX_ALERTS_PER_TENANT)
            )
        )
        .scalars()
        .all()
    )
    if not alerts:
        return 0
    have = set(
        (
            await session.execute(
                select(PlaybookDryRun.alert_id, PlaybookDryRun.playbook_id).where(PlaybookDryRun.alert_id.in_([a.id for a in alerts]))
            )
        ).all()
    )
    added = 0
    for alert in alerts:
        signals = alert_signals(alert.tags, alert.category, alert.mitre_techniques)
        for pb, reasons in would_run(playbooks, alert.severity, signals):
            if (alert.id, str(pb["id"])) in have:
                continue
            session.add(
                PlaybookDryRun(
                    tenant_id=tenant_id,
                    alert_id=alert.id,
                    playbook_id=str(pb["id"])[:120],
                    playbook_name=str(pb.get("name") or pb["id"])[:255],
                    matched_on=reasons,
                    steps=steps_of(pb),
                )
            )
            added += 1
    return added


async def run_once(session_factory: Any, fetch: FetchPlaybooks = default_fetch, now: datetime | None = None) -> dict[str, int]:
    """One pass over every flagged client. Never raises: a client whose playbooks cannot be read is skipped and tried again next pass."""
    from sqlalchemy import text  # noqa: PLC0415

    from app.db.rls_sessions import mark_platform  # noqa: PLC0415

    now = now or datetime.now(UTC)
    report = {"clients": 0, "recorded": 0, "skipped": 0}
    try:
        async with session_factory() as session:
            mark_platform(session)  # which clients are ticked is read across tenants
            tenants = await flagged_tenants(session)
    except Exception:  # noqa: BLE001 - a database that is not ready yet is tried again next pass
        LOG.warning("playbook dry runs: could not list the clients", exc_info=True)
        return report
    for tenant_id in tenants:
        try:
            playbooks = await fetch(tenant_id)
            async with session_factory() as session:
                await session.execute(text("select set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant_id)})
                report["recorded"] += await record_for_tenant(session, tenant_id, playbooks, now)
                await session.commit()
            report["clients"] += 1
        except Exception:  # noqa: BLE001
            report["skipped"] += 1
            LOG.warning("playbook dry runs: skipped client %s", tenant_id, exc_info=True)
    return report
