"""The funnel over an MSSP parent with a couple of hundred client tenants: one pass, not one query per client, and one source for the total."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import metrics as m

pytestmark = pytest.mark.asyncio

START = datetime.now(UTC) - timedelta(days=1)
END = datetime.now(UTC)


class Db:
    """Records every scalar query; answers the alert fallback and the suppression count with fixed numbers."""

    def __init__(self, fallback=111, suppressed=7):
        self.fallback, self.suppressed, self.calls = fallback, suppressed, []

    async def scalar(self, stmt, params=None):
        self.calls.append((str(stmt), params))
        return self.suppressed if "aisoc_outcome_suppressions" in str(stmt) else self.fallback


def tenants(n):
    return [uuid.uuid4() for _ in range(n)]


async def test_the_lake_total_is_the_sum_over_all_tenants_with_at_most_eight_asking_at_a_time(monkeypatch):
    monkeypatch.setattr(m, "settings", SimpleNamespace(AISOC_DISABLE_CLICKHOUSE=False))
    running = peak = 0

    async def lake(tid, start, end):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.005)
        running -= 1
        return 2

    monkeypatch.setattr(m, "_events_from_lake", lake)
    db = Db()
    assert await m._events_of_interest_total(db, tenants(200), START, END) == 400
    assert 1 < peak <= 8
    assert db.calls == [], "Postgres is not asked when the lake answered"


async def test_when_the_lake_fails_the_whole_total_comes_from_postgres_in_one_query_and_the_rest_stop_asking(monkeypatch):
    monkeypatch.setattr(m, "settings", SimpleNamespace(AISOC_DISABLE_CLICKHOUSE=False))
    asked = []

    async def lake(tid, start, end):
        asked.append(tid)
        first = len(asked) == 1
        await asyncio.sleep(0.002)
        return None if first else 5

    monkeypatch.setattr(m, "_events_from_lake", lake)
    db = Db(fallback=111)
    ids = tenants(200)
    assert await m._events_of_interest_total(db, ids, START, END) == 111, "never a mix of lake counts and Postgres counts"
    assert len(db.calls) == 1, "one query for every tenant"
    assert len(asked) <= 9, "after the first failure the remaining tenants are not sent to the lake"


async def test_with_the_lake_switched_off_every_tenant_is_counted_in_a_single_postgres_query(monkeypatch):
    monkeypatch.setattr(m, "settings", SimpleNamespace(AISOC_DISABLE_CLICKHOUSE=True))
    db = Db(fallback=42)
    assert await m._events_of_interest_total(db, tenants(50), START, END) == 42
    assert len(db.calls) == 1


async def test_repeat_suppressions_for_every_tenant_are_one_query_that_carries_all_the_tenant_ids():
    ids = tenants(200)
    db = Db(suppressed=9)
    assert await m._repeat_alerts_suppressed_total(db, ids, START, END) == 9
    assert len(db.calls) == 1 and db.calls[0][1]["tids"] == ids


async def test_a_missing_suppression_table_counts_as_zero_instead_of_failing_the_funnel():
    class Broken:
        async def scalar(self, *a, **k):
            raise RuntimeError("relation does not exist")

    assert await m._repeat_alerts_suppressed_total(Broken(), tenants(3), START, END) == 0
