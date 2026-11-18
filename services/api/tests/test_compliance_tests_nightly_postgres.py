"""Recording the automated control tests every night on a REAL Postgres (AISOC_TEST_PG_URL, AISOC_TEST_PG_APP_URL, a disposable, fully migrated database; migration 219 applied).

A person switches it on for a client; the worker records the results as evidence once a night, only for what is switched on, and the evidence it writes is the same as Record now writes.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance_tests as ep
from app.services import compliance_tests as engine
from app.workers import compliance_test_worker as worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
NOW = datetime(2026, 11, 18, 3, tzinfo=UTC)


def test_a_schedule_is_due_when_on_and_never_run_or_last_run_twenty_hours_ago():
    assert engine.nightly_due(True, None, NOW)
    assert not engine.nightly_due(False, None, NOW)
    assert not engine.nightly_due(True, NOW - timedelta(hours=19, minutes=59), NOW)
    assert engine.nightly_due(True, NOW - timedelta(hours=20), NOW)
    assert not engine.nightly_due(False, NOW - timedelta(days=9), NOW)


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(*_a, **_kw):
        return None

    monkeypatch.setattr(ep.audit, "note", noop)


@pytest.fixture
async def world():
    engine_ = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine_, expire_on_commit=False, class_=AsyncSession)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": t, "n": f"Org {t.hex[:4]}", "s": f"ct-{t.hex[:10]}"})
        await s.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2'), (:u, 'SOC2')"), {"t": a, "u": b})
        await s.execute(
            text("insert into client_m365_checks (tenant_id, source, checks, refreshed_at) values (:t, 'cipp', CAST(:c AS JSONB), now())"),
            {"t": a, "c": '[{"key": "liongard_m365_admin_mfa_policy", "status": "met", "evidence": "x"}]'},
        )
        await s.commit()
    async with factory() as s:
        yield factory, s, a, b
        await off(s)
        for table in ("aisoc_compliance_evidence", "compliance_test_schedule", "client_m365_checks", "compliance_enabled_frameworks"):
            await s.execute(text(f"delete from {table} where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine_.dispose()


def user():
    return SimpleNamespace(tenant_id=None, user_id=None, email="hal@x.com")


async def evidence(s, tenant):
    await off(s)
    return (await s.execute(text("select count(*) from aisoc_compliance_evidence where tenant_id = :t and raw_payload ->> 'source' = 'checks'"), {"t": tenant})).scalar()


async def test_switching_it_on_is_remembered_and_nothing_runs_until_the_worker_does(world):
    _f, s, a, _b = world
    await off(s)
    first = await ep.get_schedule(a, s, user())
    assert (first.nightly, first.last_run_at) == (False, None)
    await off(s)
    on = await ep.save_schedule(ep.ScheduleIn(nightly=True), a, s, user())
    assert on.nightly is True and on.last_run_at is None
    assert await evidence(s, a) == 0


async def test_the_worker_records_for_the_clients_that_are_on_and_due_and_not_again_until_twenty_hours_later(world):
    factory, s, a, b = world
    await off(s)
    await ep.save_schedule(ep.ScheduleIn(nightly=True), a, s, user())
    await off(s)
    await ep.save_schedule(ep.ScheduleIn(nightly=False), b, s, user())
    await off(s)
    out = await worker.record_once(now=NOW, factory=factory)
    assert out == {"recorded": 1, "failed": 0}, "only the client that switched it on"
    assert await evidence(s, a) > 0 and await evidence(s, b) == 0
    done = await ep.get_schedule(a, s, user())
    assert done.last_run_at == NOW and "Recorded" in (done.last_result or "")
    await off(s)
    assert await worker.record_once(now=NOW + timedelta(hours=5), factory=factory) == {"recorded": 0, "failed": 0}, "not again the same night"
    before = await evidence(s, a)
    assert await worker.record_once(now=NOW + timedelta(hours=21), factory=factory) == {"recorded": 1, "failed": 0}
    assert await evidence(s, a) == before > 0, "the earlier records were replaced, not piled up"
