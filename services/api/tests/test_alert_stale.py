"""Stale alerts: the rule that sets an alert aside, that nothing is deleted, restore and close, and when the worker looks."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.models.alert import Alert
from app.services import alert_stale as st
from app.services.alert_status import FINISHED_ALERT_STATUSES, STALE
from app.workers import suppression_sweeper as sw
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def run(coro):
    return asyncio.run(coro)


def test_the_rule_is_quiet_for_the_time_in_new_or_triaging_without_a_case_and_not_critical_or_high():
    text = sql(select(Alert.id).where(*st.stale_conditions(NOW, 30, ("critical", "high"))))
    assert "alerts.status IN ('new', 'triaging')" in text
    assert "alerts.updated_at < '2026-10-05 12:00:00+00:00'" in text
    assert "alerts.case_id IS NULL" in text
    assert "alerts.severity NOT IN ('critical', 'high')" in text
    for never in ("in_progress", "investigating", "resolved"):
        assert never not in text


def test_the_exempt_list_is_read_from_the_setting():
    assert st.exempt_severities("critical, High ,") == ("critical", "high")
    assert st.exempt_severities("") == ()


def test_stale_counts_as_finished_so_it_leaves_the_open_counts():
    assert STALE in FINISHED_ALERT_STATUSES


class Db:
    def __init__(self, ids=()):
        self.ids = list(ids)
        self.statements = []

        async def execute(statement):
            self.statements.append(statement)
            result = MagicMock()
            result.scalars.return_value.all.return_value = self.ids
            result.rowcount = len(self.ids)
            return result

        self.execute = AsyncMock(side_effect=execute)


def test_the_sweep_moves_the_alerts_aside_keeping_the_old_status_and_the_old_touch_time_and_deletes_nothing():
    db = Db([uuid.uuid4(), uuid.uuid4()])
    assert run(st.sweep_stale(db, 30, ("critical", "high"), NOW)) == 2
    update = sql(db.statements[1])
    assert update.startswith("UPDATE alerts SET status='stale'")
    assert "status_before_stale=alerts.status" in update and "updated_at=alerts.updated_at" in update
    assert "stale_at='2026-11-04 12:00:00+00:00'" in update
    assert "alerts.severity NOT IN ('critical', 'high')" in update, "the rule is checked again in the update itself"
    assert all("DELETE" not in sql(s) for s in db.statements)


def test_a_sweep_with_the_setting_off_or_nothing_quiet_does_nothing():
    off = Db([uuid.uuid4()])
    assert run(st.sweep_stale(off, 0, (), NOW)) == 0 and off.statements == []
    none = Db([])
    assert run(st.sweep_stale(none, 30, (), NOW)) == 0 and len(none.statements) == 1


def test_restore_puts_each_back_as_it_was_and_touches_it_and_only_touches_stale_alerts_of_those_clients():
    db = Db([uuid.uuid4()])
    c = uuid.uuid4()
    assert run(st.restore_stale(db, [c], None, NOW)) == 1
    text = sql(db.statements[0])
    assert "status=coalesce(alerts.status_before_stale, 'new')" in text
    assert "status_before_stale=NULL" in text and "stale_at=NULL" in text and "updated_at='2026-11-04 12:00:00+00:00'" in text
    assert f"alerts.tenant_id IN ('{c}')" in text and "alerts.status = 'stale'" in text


def test_close_only_closes_stale_alerts_and_can_be_limited_to_chosen_ones():
    db = Db([uuid.uuid4()])
    a, c = uuid.uuid4(), uuid.uuid4()
    run(st.close_stale(db, [c], [a], NOW))
    text = sql(db.statements[0])
    assert "status='closed'" in text and "alerts.status = 'stale'" in text and f"alerts.id IN ('{a}')" in text


def test_the_routes_need_the_right_permissions_and_a_confirmation():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/alert-stale")])) == {"alerts:read"}
    for path in ("/alert-stale/restore", "/alert-stale/close"):
        assert set(required_permissions(found[("POST", path)])) == {"alerts:write"}


def test_nothing_changes_without_the_confirmation():
    from app.api.v1.endpoints import alert_stale_review as ep

    db = MagicMock()
    with pytest.raises(HTTPException) as e:
        run(ep.restore(ep.Selection(), MagicMock(), NS(tenant_id=uuid.uuid4(), user_id=uuid.uuid4()), db))
    assert e.value.status_code == 422


def test_the_worker_sets_stale_alerts_aside_on_its_first_pass_and_then_only_once_an_hour(monkeypatch):
    calls = {"stale": 0, "suppress": 0}

    async def fake_stale(session, days, exempt, now=None):
        calls["stale"] += 1
        return 3

    async def fake_sweep(session):
        calls["suppress"] += 1
        return {"hidden": 0, "expired": 0}

    class Session:
        async def __aenter__(self):
            s = MagicMock()
            s.commit = AsyncMock()
            return s

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(sw, "sweep_stale", fake_stale)
    monkeypatch.setattr(sw, "sweep", fake_sweep)
    monkeypatch.setattr(sw, "mark_platform", lambda s: None)
    passes = {"n": 0}

    async def sleep(_seconds):
        passes["n"] += 1
        if passes["n"] > 61:  # the 20 s wait, then 60 one-minute passes
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run(sw.run_suppression_sweeper(sleep=sleep, session_factory=lambda: Session()))
    assert calls["suppress"] == 61
    assert calls["stale"] == 2, "once at the start and once more after sixty minutes, not every minute"
