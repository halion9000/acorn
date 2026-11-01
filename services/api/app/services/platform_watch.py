"""The platform watching itself: what is wrong right now, and what changed since the last look.

Alerts stopped for a day after the move to Azure and nobody saw it. This module is the decision part of the answer, kept pure so it is cheap to test: ``evaluate`` turns plain measurements into findings, ``changes`` says which findings are new and which cleared. The worker (app/workers/platform_watch_worker.py)
reads the measurements, remembers the last findings, and emails the platform administrators about changes only, so a problem that stays is told once, not every few minutes.

Not covered: a container that keeps restarting. The API has no view of the Docker host, so that needs a check on the host (see the Azure runbook).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

CORE_FEED_SILENT_AFTER = timedelta(minutes=15)
DISK_WARN_FREE_PERCENT = 15.0
DISK_CRIT_FREE_PERCENT = 8.0
MEMORY_WARN_AVAILABLE_PERCENT = 10.0


@dataclass(frozen=True)
class Finding:
    key: str  # stable identity, so the same problem is the same finding next time
    severity: str  # "warning" | "critical"
    message: str


@dataclass(frozen=True)
class ConnectorSeen:
    name: str
    tenant_name: str
    last_event_at: datetime | None


def _aware(moment: datetime | None) -> datetime | None:
    return moment if moment is None or moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _ago(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 90:
        return f"{minutes} minutes"
    hours = minutes // 60
    return f"{hours} hours" if hours < 48 else f"{hours // 24} days"


def evaluate(
    *,
    now: datetime,
    core_feed_last_report: datetime | None,
    core_feed_sources: int,
    connectors: list[ConnectorSeen],
    connector_silent_after: timedelta,
    disk_free_percent: float | None,
    memory_available_percent: float | None,
) -> list[Finding]:
    """Every problem visible in these measurements. A measurement that could not be taken (None) produces no finding: a blind spot is not an alarm."""
    found: list[Finding] = []

    # CORE reports on every run, even a run that found nothing new, so silence means CORE is off, asleep, or cannot reach this server. ``core_feed_sources == 0`` means CORE was never connected: nothing to warn about.
    if core_feed_sources > 0:
        last = _aware(core_feed_last_report)
        if last is None:
            found.append(Finding("core_feed", "critical", "CORE is set up but has never reported. Nothing from Huntress, Petra, NinjaOne and the other tools is arriving."))
        elif now - last > CORE_FEED_SILENT_AFTER:
            found.append(
                Finding(
                    "core_feed",
                    "critical",
                    f"CORE has not reported for {_ago(now - last)}. Nothing from Huntress, Petra, NinjaOne and the other tools is arriving. Check that CORE is running and can reach this server.",
                )
            )

    # A connector that had events and then went quiet for hours. One that never had an event is just new, not silent.
    for c in connectors:
        last = _aware(c.last_event_at)
        if last is not None and now - last > connector_silent_after:
            found.append(
                Finding(
                    f"connector:{c.tenant_name}:{c.name}",
                    "warning",
                    f"{c.name} for {c.tenant_name} has sent nothing for {_ago(now - last)}.",
                )
            )

    if disk_free_percent is not None and disk_free_percent < DISK_WARN_FREE_PERCENT:
        severity = "critical" if disk_free_percent < DISK_CRIT_FREE_PERCENT else "warning"
        found.append(Finding("disk", severity, f"The server disk has {disk_free_percent:.0f}% free."))
    if memory_available_percent is not None and memory_available_percent < MEMORY_WARN_AVAILABLE_PERCENT:
        found.append(Finding("memory", "warning", f"The server has {memory_available_percent:.0f}% of its memory available."))

    return found


def changes(previous: dict[str, Finding], current: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """(new findings, findings that cleared) between the last look and this one. A finding whose severity went up counts as new, so a warning that becomes critical is told again."""
    now_by_key = {f.key: f for f in current}
    new = [f for f in current if f.key not in previous or (previous[f.key].severity != f.severity and f.severity == "critical")]
    cleared = [f for k, f in previous.items() if k not in now_by_key]
    return new, cleared


def compose(new: list[Finding], cleared: list[Finding], *, server_name: str) -> tuple[str, str]:
    """Subject and plain-text body for one message about what changed."""
    critical = any(f.severity == "critical" for f in new)
    if new:
        subject = f"[A.C.O.R.N] {'ACTION NEEDED' if critical else 'Warning'}: {new[0].message.split('.')[0]}" + (f" (+{len(new) - 1} more)" if len(new) > 1 else "")
    else:
        subject = f"[A.C.O.R.N] Back to normal: {cleared[0].message.split('.')[0]}" + (f" (+{len(cleared) - 1} more)" if len(cleared) > 1 else "")
    lines = [f"A.C.O.R.N on {server_name} noticed a change.", ""]
    if new:
        lines.append("New problems:")
        lines += [f"  - [{f.severity}] {f.message}" for f in new]
        lines.append("")
    if cleared:
        lines.append("No longer a problem:")
        lines += [f"  - {f.message}" for f in cleared]
        lines.append("")
    lines.append("You get one message per change, not one per check.")
    return subject, "\n".join(lines)
