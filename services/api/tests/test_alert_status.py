"""One list of finished alert statuses, used everywhere.

Eight modules kept their own copies and they disagreed. A bulk close writes ``false_positive``, so the shift handoff (``resolved``, ``fp``, ``closed`` only), the executive digest (the same three), Leafy's "only open" search (no ``fp``, no ``suppressed``) and the KPI bar's false-positive
rate (``fp`` only) all treated those alerts as open work or as no false positives at all.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.deps import CurrentUser
from app.api.v1.endpoints import alerts, devices
from app.api.v1.endpoints.shifts import list_handoff_items
from app.services import alert_queue, alert_suppression, core_feed_cases, executive_digest, mssp_snapshots, sla
from app.services.alert_status import FALSE_POSITIVE_STATUSES, FINISHED_ALERT_STATUSES, HANDLED_ALERT_STATUSES, is_finished, sql_in
from sqlalchemy.dialects import postgresql


def test_the_lists_say_what_they_mean():
    assert set(FALSE_POSITIVE_STATUSES) == {"false_positive", "fp"}
    assert set(HANDLED_ALERT_STATUSES) == {"resolved", "closed", "false_positive", "fp"}
    assert set(FINISHED_ALERT_STATUSES) == {"resolved", "closed", "false_positive", "fp", "suppressed"}
    assert all(is_finished(s) for s in FINISHED_ALERT_STATUSES)
    assert not any(is_finished(s) for s in ("new", "triaging", "in_progress", "", None))
    assert sql_in(("a", "b'c")) == "'a','b''c'"


def test_every_module_uses_the_same_finished_statuses():
    from app import copilot_tools

    for name, value in {
        "alerts": alerts.FINISHED_STATUSES,
        "devices": devices._CLOSED,
        "copilot": copilot_tools._CLOSED_STATUSES,
        "suppression": alert_suppression._FINISHED,
        "core_feed_cases": core_feed_cases.FINISHED_ALERT,
        "mssp_snapshots": mssp_snapshots.FINISHED_ALERT,
        "queue": alert_queue.QUEUE_CLOSED_STATUSES,
    }.items():
        assert set(value) == set(FINISHED_ALERT_STATUSES), name


def _compiled(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_the_shift_handoff_does_not_list_a_false_positive_or_suppressed_alert_as_open_work():
    executed: list[str] = []

    async def _execute(clause: Any, params: dict | None = None, *a: Any, **k: Any) -> MagicMock:
        executed.append(re.sub(r"\s+", " ", str(clause)))
        result = MagicMock()
        result.fetchall = MagicMock(return_value=[])
        return result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    user = CurrentUser(user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="analyst", email="a@example.com")
    await list_handoff_items(current_user=user, db=db, priority=None, limit=50)
    alert_sql = next(s for s in executed if "FROM alerts" in s)
    listed = re.search(r"status NOT IN \(([^)]*)\)", alert_sql)
    assert listed, alert_sql
    assert set(re.findall(r"'([^']+)'", listed.group(1))) == set(FINISHED_ALERT_STATUSES)


@pytest.mark.asyncio
async def test_the_executive_digest_counts_only_unfinished_alerts_as_open():
    seen: list[str] = []

    async def _scalar(stmt: Any) -> int:
        seen.append(_compiled(stmt))
        return 0

    db = SimpleNamespace(scalar=_scalar)
    await executive_digest._count_open_alerts(db, uuid.uuid4(), datetime.now(UTC))  # type: ignore[arg-type]
    assert len(seen) == 1
    for status in FINISHED_ALERT_STATUSES:
        assert f"'{status}'" in seen[0], status


@pytest.mark.asyncio
async def test_the_kpi_bar_counts_a_bulk_close_as_false_positive():
    """A bulk close writes ``false_positive``; the rate counted only ``fp`` and read 0%."""

    async def _execute(stmt: Any) -> MagicMock:
        text = _compiled(stmt)
        result = MagicMock()
        # 10 alerts in the window, 4 of them closed as false positives.
        count = 4 if "false_positive" in text else 10 if "count(alerts.id)" in text.lower() or "count(*)" in text.lower() else 0
        result.scalar_one = MagicMock(return_value=count)
        return result

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_execute)
    targets = {
        "false_positive_rate_max_pct": 50.0,
        "alert_to_incident_ratio_min": 1.0,
        "mitre_technique_tagging_min_pct": 0.0,
        "mitre_subtechnique_tagging_min_pct": 0.0,
    }
    out = await sla._compute_kpi_bar(db, uuid.uuid4(), datetime.now(UTC), targets)
    assert out["observed"]["false_positives"] == 4
    assert out["observed"]["false_positive_rate_pct"] == 40.0
