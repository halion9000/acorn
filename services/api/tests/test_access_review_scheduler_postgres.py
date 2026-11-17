"""The scheduler on a REAL Postgres: a due schedule starts a review with the people held and moves its day, a schedule not yet due or switched off starts nothing, a system with nobody says so and keeps its day,
and one tenant's schedule never reads another's people. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database, migrations 206 applied)."""

import os
import uuid
from datetime import date

import pytest
from app.workers import access_review_scheduler as w
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
TODAY = date(2026, 11, 17)


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(*_a, **_k):
        return None

    import app.services.compliance_audit as audit

    monkeypatch.setattr(audit, "note", noop)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"ar-{t.hex[:10]}"})
        for t, who in ((a, "ann@x.com"), (a, "bob@x.com"), (b, "other@y.com")):
            await s.execute(
                text("insert into identity_sources (tenant_id, vendor, external_id, email, kind, details) values (:t, 'Acme VPN', :e, :e, 'user', '{}')"),
                {"t": t, "e": who},
            )
        await s.commit()
    yield factory, a, b
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for tbl in ("access_review_entries", "access_reviews", "access_review_schedules", "identity_sources"):
            await s.execute(text(f"delete from {tbl} where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


async def add_schedule(factory, tenant, system, next_start, enabled=True, every=90):
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        sid = uuid.uuid4()
        await s.execute(
            text("insert into access_review_schedules (id, tenant_id, system, reviewer, every_days, next_start, enabled) values (:i, :t, :s, 'hal@x', :e, :n, :en)"),
            {"i": sid, "t": tenant, "s": system, "e": every, "n": next_start, "en": enabled},
        )
        await s.commit()
    return sid


async def rows(factory, sql, **p):
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        return (await s.execute(text(sql), p)).all()


async def test_a_due_schedule_starts_a_review_of_its_own_tenants_people_and_moves_its_day(world):
    factory, a, b = world
    sid = await add_schedule(factory, a, "Acme VPN", date(2026, 11, 1))
    out = await w.start_due(TODAY, factory=factory)
    assert out == {"started": 1, "empty": 0, "failed": 0}
    review = (await rows(factory, "select name, reviewer, due_date, created_by, id from access_reviews where tenant_id = :t", t=a))[0]
    assert review[:4] == ("Q4 2026 access review: Acme VPN", "hal@x", date(2026, 12, 17), "scheduled")
    people = await rows(factory, "select person from access_review_entries where review_id = :r order by person", r=review[4])
    assert [p[0] for p in people] == ["ann@x.com", "bob@x.com"], "only this tenant's people"
    sched = (await rows(factory, "select next_start, last_review_id, last_error from access_review_schedules where id = :i", i=sid))[0]
    assert sched[0] == date(2027, 2, 15) and sched[1] == review[4] and sched[2] is None
    again = await w.start_due(TODAY, factory=factory)
    assert again["started"] == 0, "not due again until the new day"


async def test_not_due_or_switched_off_starts_nothing_and_a_system_with_nobody_says_so(world):
    factory, a, b = world
    await add_schedule(factory, a, "Acme VPN", date(2026, 11, 18))
    await add_schedule(factory, a, "Other tool", date(2026, 11, 1), enabled=False)
    empty = await add_schedule(factory, b, "No people tool", date(2026, 11, 1))
    out = await w.start_due(TODAY, factory=factory)
    assert out == {"started": 0, "empty": 1, "failed": 0}
    assert not await rows(factory, "select 1 from access_reviews where tenant_id in (:a, :b)", a=a, b=b)
    sched = (await rows(factory, "select next_start, last_error from access_review_schedules where id = :i", i=empty))[0]
    assert sched[0] == date(2026, 11, 1), "keeps its day, tries again next hour"
    assert "No people tool" in sched[1]


async def test_the_routes_keep_one_schedule_per_system_and_refuse_a_past_start_day(world):
    from types import SimpleNamespace

    from app.api.v1.endpoints import access_reviews as ep
    from fastapi import HTTPException

    factory, a, b = world
    user = SimpleNamespace(tenant_id=a, user_id=None, email="hal@x")
    async with factory() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        first = await ep.put_schedule(ep.ScheduleIn(system="Acme VPN", reviewer="hal@x"), a, s, user)
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        second = await ep.put_schedule(ep.ScheduleIn(system="Acme VPN", reviewer="amy@x", every_days=30, enabled=False), a, s, user)
        assert second.id == first.id and (second.reviewer, second.every_days, second.enabled) == ("amy@x", 30, False)
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        with pytest.raises(HTTPException) as e:
            await ep.put_schedule(ep.ScheduleIn(system="Acme VPN", first_start=date(2020, 1, 1)), a, s, user)
        assert e.value.status_code == 422
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        assert [r.system for r in await ep.list_schedules(a, s, user)] == ["Acme VPN"]
        assert await ep.list_schedules(b, s, user) == [], "another owner sees none"
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await ep.delete_schedule(first.id, a, s, user)
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        assert await ep.list_schedules(a, s, user) == []
