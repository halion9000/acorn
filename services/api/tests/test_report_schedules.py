"""Scheduled reports: the slot rules (pure), then the endpoints and the worker on a REAL Postgres (AISOC_TEST_PG_URL, migration 226 applied)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import report_schedules as ep
from app.models.report_schedule import ReportSchedule
from app.services import report_scheduler as rs
from app.workers import report_schedule_worker as worker
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def U(*a):
    return datetime(*a, tzinfo=UTC)


def test_the_latest_slot_of_a_daily_weekly_and_monthly_schedule():
    now = U(2026, 11, 18, 9, 30)  # a Wednesday
    assert rs.slot_before("daily", 0, 7, now) == U(2026, 11, 18, 7)
    assert rs.slot_before("daily", 0, 12, now) == U(2026, 11, 17, 12), "today's hour has not come: yesterday's is the latest"
    assert rs.slot_before("weekly", 0, 7, now) == U(2026, 11, 16, 7), "Monday of this week"
    assert rs.slot_before("weekly", 2, 12, now) == U(2026, 11, 11, 12), "Wednesday noon has not come yet: last week's"
    assert rs.slot_before("monthly", 5, 7, now) == U(2026, 11, 5, 7)
    assert rs.slot_before("monthly", 25, 7, now) == U(2026, 10, 25, 7), "the 25th of this month has not come"
    assert rs.slot_before("monthly", 5, 7, U(2026, 1, 3, 9)) == U(2025, 12, 5, 7), "across a year"


def test_a_schedule_is_due_only_when_its_latest_slot_passed_since_it_last_ran():
    now = U(2026, 11, 18, 9)
    assert rs.due("daily", 0, 7, U(2026, 11, 17, 7), now)
    assert not rs.due("daily", 0, 7, U(2026, 11, 18, 7, 5), now), "already ran after today's slot"
    assert rs.due("weekly", 0, 7, U(2026, 11, 9, 7), now)
    assert not rs.due("weekly", 0, 7, U(2026, 11, 16, 8), now)
    assert rs.due("daily", 0, 7, None, now)


def test_addresses_are_cleaned_and_capped():
    assert rs.clean_emails([" Amy@X.com ", "amy@x.com", "nope", "a b@x.com", "bob@x"]) == ["amy@x.com"]
    assert len(rs.clean_emails([f"u{i}@x.com" for i in range(30)])) == rs.MAX_EMAILS


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


class FakeMailer:
    def __init__(self, configured=True):
        self.configured = configured
        self.sent = []

    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))


@pytest.fixture
async def world(monkeypatch):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": t, "n": f"Org {t.hex[:4]}", "s": f"rs-{t.hex[:10]}"})
        await s.commit()

    async def render(db, tenant, now):
        return ("Subject", "Body A") if tenant == a else None

    monkeypatch.setitem(rs.KINDS, "compliance_actions", ("Compliance action items", render))
    async with factory() as s:
        yield factory, s, a, b
        await off(s)
        await s.execute(text("delete from report_schedules where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def user():
    return SimpleNamespace(tenant_id=None, user_id=None, email="hal@x.com")


def schedule(tenant, name, **over):
    base = {"id": uuid.uuid4(), "tenant_id": tenant, "name": name, "report_kind": "compliance_actions", "emails": ["amy@x.com"], "frequency": "daily", "day": 0, "hour_utc": 7}
    base.update(over)
    return ReportSchedule(**base)


@needs_pg
@pytest.mark.asyncio
async def test_a_schedule_is_checked_saved_changed_and_deleted(world):
    _f, s, a, _b = world
    await off(s)
    for bad in (
        ep.ScheduleIn(name="Weekly", report_kind="nope", emails=["a@x.com"], frequency="daily"),
        ep.ScheduleIn(name="Weekly", report_kind="compliance_actions", emails=["nope"], frequency="daily"),
        ep.ScheduleIn(name="Weekly", report_kind="compliance_actions", emails=["a@x.com"], frequency="weekly", day=9),
        ep.ScheduleIn(name="Monthly", report_kind="compliance_actions", emails=["a@x.com"], frequency="monthly", day=0),
    ):
        with pytest.raises(HTTPException) as e:
            await ep.create_schedule(bad, a, s, user())
        assert e.value.status_code == 422
        await off(s)
    made = await ep.create_schedule(ep.ScheduleIn(name="Monday digest", report_kind="compliance_actions", emails=[" Amy@X.com "], frequency="weekly", day=0, hour_utc=7), a, s, user())
    assert made.emails == ["amy@x.com"] and made.report_label == "Compliance action items"
    assert made.last_run_at is not None, "a new schedule first runs at its next slot, not at once"
    await off(s)
    listed = await ep.list_schedules(a, s, user())
    assert [x.name for x in listed.schedules] == ["Monday digest"] and "compliance_actions" in [k["kind"] for k in listed.kinds]
    await off(s)
    changed = await ep.patch_schedule(made.id, ep.SchedulePatch(frequency="monthly", day=3, enabled=False), a, s, user())
    assert (changed.frequency, changed.day, changed.enabled) == ("monthly", 3, False)
    await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.patch_schedule(made.id, ep.SchedulePatch(frequency="weekly"), a, s, user())  # day 3 is a fine weekday
        await ep.patch_schedule(made.id, ep.SchedulePatch(day=20), a, s, user())  # but 20 is not a weekday
    assert e.value.status_code == 422
    await off(s)
    await ep.delete_schedule(made.id, a, s, user())
    await off(s)
    assert (await ep.list_schedules(a, s, user())).schedules == []


@needs_pg
@pytest.mark.asyncio
async def test_the_worker_sends_what_is_due_records_it_and_does_not_send_it_twice(world):
    factory, s, a, b = world
    await off(s)
    now = U(2026, 11, 18, 9)
    s.add(schedule(a, "Daily", last_run_at=now - timedelta(days=1)))
    s.add(schedule(a, "Off", enabled=False, last_run_at=None))
    s.add(schedule(b, "Quiet", emails=["bob@x.com"], last_run_at=now - timedelta(days=1)))
    await s.commit()
    mailer = FakeMailer()
    out = await worker.send_once(now=now, factory=factory, mailer=mailer)
    assert out == {"handled": 2, "failed": 0}
    assert mailer.sent == [(["amy@x.com"], "Daily: Subject", "Body A")], "a switched-off schedule and one with nothing to report send nothing"
    again = await worker.send_once(now=now + timedelta(hours=1), factory=factory, mailer=mailer)
    assert again == {"handled": 0, "failed": 0} and len(mailer.sent) == 1
    await off(s)
    results = dict((await s.execute(text("select name, last_result from report_schedules where tenant_id in (:a, :b)"), {"a": a, "b": b})).all())
    assert results["Daily"] == "Sent to 1." and results["Quiet"] == "Nothing to report, so nothing was sent."


@needs_pg
@pytest.mark.asyncio
async def test_a_send_that_cannot_go_is_not_marked_as_run_so_the_next_pass_tries_again(world):
    factory, s, a, _b = world
    await off(s)
    now = U(2026, 11, 18, 9)
    s.add(schedule(a, "Daily", last_run_at=now - timedelta(days=1)))
    await s.commit()
    await worker.send_once(now=now, factory=factory, mailer=FakeMailer(configured=False))
    await off(s)
    row = (await s.execute(text("select last_result, last_run_at from report_schedules where tenant_id = :a"), {"a": a})).one()
    assert row.last_result == "The mail credentials are not set." and row.last_run_at < now - timedelta(hours=1)
    mailer = FakeMailer()
    await worker.send_once(now=now + timedelta(hours=1), factory=factory, mailer=mailer)
    assert len(mailer.sent) == 1
