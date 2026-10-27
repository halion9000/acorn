"""The same-name merge runs behind the device report: at most every ten minutes per client, and a failure there never fails the report."""

import contextlib
import uuid

from app.api.v1.endpoints import devices as ep


class FakeDb:
    @contextlib.asynccontextmanager
    async def begin_nested(self):
        yield


def _patch(monkeypatch, behaviour):
    calls = []

    @contextlib.asynccontextmanager
    async def acting(_db, tid):
        yield

    async def fake(_db, tid, *_a, **_k):
        calls.append(tid)
        return behaviour(tid)

    monkeypatch.setattr(ep, "acting_as_tenant", acting)
    monkeypatch.setattr(ep, "auto_merge_same_name", fake)
    ep._auto_merge_last.clear()
    return calls


async def test_a_client_is_checked_at_most_every_ten_minutes(monkeypatch):
    calls = _patch(monkeypatch, lambda tid: 2)
    t = uuid.uuid4()
    assert await ep._auto_merge_touched(FakeDb(), [t], now=1000.0) == 2
    assert await ep._auto_merge_touched(FakeDb(), [t], now=1000.0 + 599) == 0
    assert await ep._auto_merge_touched(FakeDb(), [t], now=1000.0 + 601) == 2
    assert calls == [t, t]


async def test_each_client_has_its_own_clock_and_the_merges_add_up(monkeypatch):
    calls = _patch(monkeypatch, lambda tid: 1)
    a, b = uuid.uuid4(), uuid.uuid4()
    assert await ep._auto_merge_touched(FakeDb(), [a, b], now=5.0) == 2
    assert await ep._auto_merge_touched(FakeDb(), [a, b], now=6.0) == 0
    assert sorted(calls) == sorted([a, b])


async def test_a_failure_is_skipped_and_the_other_clients_are_still_checked(monkeypatch):
    bad, good = uuid.uuid4(), uuid.uuid4()

    def behaviour(tid):
        if tid == bad:
            raise RuntimeError("boom")
        return 3

    _patch(monkeypatch, behaviour)
    assert await ep._auto_merge_touched(FakeDb(), [bad, good], now=1.0) == 3


async def test_one_report_checks_only_a_few_clients_and_the_rest_stay_due_for_the_next_one(monkeypatch):
    calls = _patch(monkeypatch, lambda tid: 1)
    tenants = [uuid.uuid4() for _ in range(ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT * 2 + 3)]
    first = await ep._auto_merge_touched(FakeDb(), tenants, now=10.0)
    assert first == ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT and calls == tenants[: ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT]
    second = await ep._auto_merge_touched(FakeDb(), tenants, now=11.0)
    assert second == ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT, "the next report carries on with the clients not reached"
    assert calls[ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT : ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT * 2] == tenants[ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT : ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT * 2]
    third = await ep._auto_merge_touched(FakeDb(), tenants, now=12.0)
    assert third == 3 and sorted(calls) == sorted(tenants), "every client is reached, each once"
    assert await ep._auto_merge_touched(FakeDb(), tenants, now=13.0) == 0


async def test_clients_that_are_not_due_do_not_use_up_the_limit(monkeypatch):
    calls = _patch(monkeypatch, lambda tid: 1)
    recent = [uuid.uuid4() for _ in range(ep.AUTO_MERGE_MAX_CLIENTS_PER_REPORT + 2)]
    fresh = [uuid.uuid4() for _ in range(3)]
    for t in recent:
        ep._auto_merge_last[t] = 9.0
    assert await ep._auto_merge_touched(FakeDb(), [*recent, *fresh], now=10.0) == 3
    assert calls == fresh
