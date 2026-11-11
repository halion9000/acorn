"""The trend rules behind a client's progress report, and the endpoint that serves them."""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import mssp
from app.db.database import Base
from app.models.mssp import MSSPTenantMetrics
from app.models.tenant import Tenant
from app.services.measure_trend import SILENT_AFTER_DAYS, daily_series, summarise
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

END = date(2026, 11, 10)
START = date(2026, 8, 13)  # 90 days


def at(d: date, hour: int = 12) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=UTC)


def test_the_last_snapshot_of_a_day_is_that_days_figure():
    s = daily_series([(at(END, 8), 5), (at(END, 20), 9), (at(END, 14), 7)], START, END)
    assert s == [(END, 9.0)]


def test_a_day_with_no_snapshot_repeats_the_last_figure_and_the_line_starts_at_the_first_recording():
    s = daily_series([(at(date(2026, 11, 7)), 4), (at(date(2026, 11, 9)), 6)], START, END)
    assert s == [(date(2026, 11, 7), 4.0), (date(2026, 11, 8), 4.0), (date(2026, 11, 9), 6.0), (date(2026, 11, 10), 6.0)]


def test_nothing_is_invented_before_the_first_recording_or_for_a_figure_that_is_none():
    assert daily_series([(at(END), None)], START, END) == []
    assert daily_series([], START, END) == []


def test_a_measure_silent_for_more_than_a_week_is_left_out_but_exactly_a_week_is_kept():
    old = END - timedelta(days=SILENT_AFTER_DAYS + 1)
    assert daily_series([(at(old), 3)], START, END) == []
    edge = END - timedelta(days=SILENT_AFTER_DAYS)
    assert daily_series([(at(edge), 3)], START, END)[-1] == (END, 3.0)


def test_snapshots_outside_the_period_do_not_count():
    assert daily_series([(at(START - timedelta(days=1)), 99)], START, END) == []


def test_the_summary_is_start_now_change_lowest_highest():
    series = [(date(2026, 11, 8), 10.0), (date(2026, 11, 9), 4.0), (date(2026, 11, 10), 7.0)]
    s = summarise(series)
    assert (s.start, s.now, s.change, s.lowest, s.highest, s.last_recorded) == (10.0, 7.0, -3.0, 4.0, 10.0, date(2026, 11, 10))
    assert summarise([]) is None


# ── the endpoint ──
TABLES = [m.__table__ for m in (Tenant, MSSPTenantMetrics)]


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


async def tenant(s, name, parent=None):
    t = Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(), parent_tenant_id=parent)
    s.add(t)
    await s.flush()
    return t


def snap(t, days_ago, **kw):
    return MSSPTenantMetrics(id=uuid.uuid4(), tenant_id=t.id, snapshot_at=datetime.now(UTC) - timedelta(days=days_ago), raw_data={}, **kw)


def test_progress_reports_each_measure_and_says_not_recorded_for_one_with_no_figures():
    async def body(s):
        parent = await tenant(s, "MSSP")
        child = await tenant(s, "Acme", parent.id)
        s.add_all(
            [
                snap(child, 10, open_alerts=12, critical_alerts=3, health_score=None),
                snap(child, 0, open_alerts=5, critical_alerts=0, health_score=None),
            ]
        )
        await s.commit()
        return await mssp.child_progress(child.id, days=90, db=s, current_user=SimpleNamespace(tenant_id=parent.id))

    out = run(body)
    by = {m["key"]: m for m in out["measures"]}
    assert by["open_alerts"]["recorded"] and by["open_alerts"]["summary"]["start"] == 12 and by["open_alerts"]["summary"]["now"] == 5
    assert by["open_alerts"]["summary"]["change"] == -7
    assert by["critical_alerts"]["summary"]["lowest"] == 0
    assert by["health_score"]["recorded"] is False and by["health_score"]["summary"] is None and by["health_score"]["series"] == []
    assert len(by["open_alerts"]["series"]) == 11  # ten days ago through today


def test_progress_is_only_for_the_callers_own_clients():
    async def body(s):
        parent = await tenant(s, "MSSP")
        other_parent = await tenant(s, "Other MSSP")
        theirs = await tenant(s, "Theirs", other_parent.id)
        s.add(snap(theirs, 0, open_alerts=1))
        await s.commit()
        with pytest.raises(HTTPException) as e:
            await mssp.child_progress(theirs.id, days=90, db=s, current_user=SimpleNamespace(tenant_id=parent.id))
        return e.value.status_code

    assert run(body) == 404
