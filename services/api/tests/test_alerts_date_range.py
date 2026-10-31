"""The alerts list can be limited to a date range (when the alert was received), and the header counts follow the same range."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alerts as ep
from app.db.database import Base
from app.models.alert import Alert
from app.models.tenant import Tenant
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@contextlib.asynccontextmanager
async def no_scope(_db, _tenant_id):
    yield


ep.acting_as_tenant = no_scope  # the real one sets a Postgres setting; these tests run on SQLite


def run(fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, Alert.__table__]))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def tenant(name, parent=None):
    return Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(), parent_tenant_id=parent)


def alert(t, title, days_ago, severity="medium"):
    at = NOW - timedelta(days=days_ago)
    return Alert(
        tenant_id=t.id, title=title, description="", severity=severity, status="new", priority=3, created_at=at, updated_at=at,
        event_time=at, first_seen=at, last_seen=at, mitre_tactics=[], mitre_techniques=[], ai_recommendations=[],
        affected_ips=[], affected_hosts=[], affected_users=[], tags=[], connector_type="Generic Generic JSON", raw_event={},
    )  # fmt: skip


async def seed(s):
    parent = tenant("Live Oak")
    client = tenant("Setpoint", parent.id)
    s.add_all([parent, client])
    await s.flush()
    s.add_all(
        [
            alert(parent, "today", 0, "critical"),
            alert(parent, "yesterday", 1),
            alert(client, "three-days", 3, "high"),
            alert(client, "ten-days", 10),
            alert(client, "forty-days", 40, "critical"),
        ]
    )
    await s.commit()
    return parent, client


def call(s, tenant_id, **kw):
    user = SimpleNamespace(tenant_id=tenant_id, user_id=uuid.uuid4())
    args = {
        "page": 1, "page_size": 25, "severity": None, "status": None, "category": None, "assigned_to_me": False, "search": None,
        "min_confidence": None, "confidence_label": None, "source": None, "client_id": None, "device": None, "ticket": None,
        "since": None, "until": None,
    }  # fmt: skip
    args.update(kw)
    return ep.list_alerts(user, s, **args)


def titles(out):
    return [i.title for i in out.items]


def test_no_dates_means_everything():
    async def go(s):
        parent, _ = await seed(s)
        out = await call(s, parent.id)
        assert out.total == 5

    run(go)


def test_since_and_until_cut_the_list_across_the_owner_and_its_clients():
    async def go(s):
        parent, _ = await seed(s)
        last_week = await call(s, parent.id, since=NOW - timedelta(days=7))
        assert titles(last_week) == ["today", "yesterday", "three-days"]
        only_yesterday = await call(s, parent.id, since=NOW - timedelta(days=1, hours=1), until=NOW - timedelta(hours=1))
        assert titles(only_yesterday) == ["yesterday"]
        old = await call(s, parent.id, until=NOW - timedelta(days=30))
        assert titles(old) == ["forty-days"]

    run(go)


def test_the_start_is_included_and_the_end_is_not():
    async def go(s):
        parent, _ = await seed(s)
        exactly = NOW - timedelta(days=1)
        assert "yesterday" in titles(await call(s, parent.id, since=exactly))
        assert "yesterday" not in titles(await call(s, parent.id, until=exactly))

    run(go)


def test_the_header_counts_follow_the_dates_and_combine_with_the_other_filters():
    async def go(s):
        parent, _ = await seed(s)
        everything = await call(s, parent.id)
        assert (everything.summary.total, everything.summary.critical) == (5, 2)
        recent = await call(s, parent.id, since=NOW - timedelta(days=7))
        assert (recent.summary.total, recent.summary.critical, recent.summary.high) == (3, 1, 1)
        recent_critical = await call(s, parent.id, since=NOW - timedelta(days=7), severity="critical")
        assert titles(recent_critical) == ["today"]
        assert recent_critical.summary.total == 3, "the counts do not change with the severity buttons"

    run(go)


def test_a_time_without_a_zone_counts_as_utc_and_a_backwards_range_is_refused():
    async def go(s):
        parent, _ = await seed(s)
        naive = (NOW - timedelta(days=7)).replace(tzinfo=None)
        assert titles(await call(s, parent.id, since=naive)) == ["today", "yesterday", "three-days"]
        with pytest.raises(HTTPException) as e:
            await call(s, parent.id, since=NOW, until=NOW - timedelta(days=1))
        assert e.value.status_code == 422
        with pytest.raises(HTTPException):
            await call(s, parent.id, since=NOW, until=NOW)

    run(go)


def test_a_range_with_nothing_in_it_is_an_empty_list_not_an_error():
    async def go(s):
        parent, _ = await seed(s)
        out = await call(s, parent.id, since=NOW + timedelta(days=1))
        assert out.items == [] and out.total == 0 and out.summary.total == 0

    run(go)
