"""The managed-clients list says how many alerts each client has set aside as stale; when that cannot be read it says so (None), never zero."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import mssp
from app.db.database import Base
from app.models.client_alias import ClientAlias
from app.models.mssp import MSSPTenantMetrics
from app.models.tenant import Tenant
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, MSSPTenantMetrics, ClientAlias)]


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    import app.db.rls_scope as scope

    @contextlib.asynccontextmanager
    async def no_rls(_db):
        yield

    monkeypatch.setattr(scope, "cross_tenant_reads", no_rls)

    async def no_connectors(_db, _ids):
        return {}

    monkeypatch.setattr(mssp, "_connector_health", no_connectors)  # not what is tested here


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


async def make(s, name, parent=None):
    t = Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(), parent_tenant_id=parent)
    s.add(t)
    await s.flush()
    return t


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Db:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom, self.asked = rows or [], boom, 0

    async def execute(self, _stmt):
        self.asked += 1
        if self.boom:
            raise RuntimeError("alerts is unreadable")
        return Rows(self.rows)


def test_counts_are_per_client_and_nothing_is_asked_for_no_clients():
    a, b = uuid.uuid4(), uuid.uuid4()
    db = Db([(a, 7), (b, 1)])
    assert asyncio.run(mssp._stale_counts(db, [a, b, uuid.uuid4()])) == {a: 7, b: 1}
    none = Db()
    assert asyncio.run(mssp._stale_counts(none, [])) == {} and none.asked == 0


def test_the_list_gives_each_client_its_count_zero_when_it_has_none(monkeypatch):
    seen = {}

    async def counts(_db, ids):
        seen["ids"] = ids
        return {ids[0]: 12}

    monkeypatch.setattr(mssp, "_stale_counts", counts)

    async def body(s):
        parent = await make(s, "Parent")
        await make(s, "Acme", parent.id)
        await make(s, "Birch", parent.id)
        other = await make(s, "Other")
        await make(s, "Theirs", other.id)
        await s.commit()
        return await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=SimpleNamespace(tenant_id=parent.id))

    rows = run(body)
    assert len(seen["ids"]) == 2, "only this MSSP's own clients are counted"
    assert {r.name: r.stale_alerts for r in rows} == {"Acme": 12, "Birch": 0}


def test_a_failed_read_gives_unknown_not_zero_and_the_list_still_loads(monkeypatch):
    async def broken(_db, _ids):
        raise RuntimeError("no alerts table")

    monkeypatch.setattr(mssp, "_stale_counts", broken)

    async def body(s):
        parent = await make(s, "Parent")
        await make(s, "Acme", parent.id)
        await s.commit()
        return await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=SimpleNamespace(tenant_id=parent.id))

    rows = run(body)
    assert [(r.name, r.stale_alerts) for r in rows] == [("Acme", None)]


# ---- remote tools nobody has reviewed ------------------------------------------------------------------------------------------------------------------

from app.api.v1.endpoints import remote_tools as rtep  # noqa: E402


def seen(tenant, key):
    return SimpleNamespace(tenant_id=tenant, tool_key=key)


def test_unreviewed_tools_are_counted_once_per_tool_per_client_and_a_rule_for_the_client_or_everyone_settles_it():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sightings = [
        seen(a, "anydesk"),
        seen(a, "anydesk"),
        seen(a, "teamviewer"),
        seen(b, "anydesk"),
        seen(b, "teamviewer"),
        seen(c, "anydesk"),
        seen(a, "not_in_the_catalog"),
    ]
    rules = {("teamviewer", None): "allowed", ("anydesk", b): "blocked"}
    assert rtep.unreviewed_tools_by_client(sightings, rules) == {
        a: 1,
        c: 1,
    }, "two installs of one tool are one tool; allowed for everyone and blocked for b are both reviewed; unknown tools are ignored"
    assert rtep.unreviewed_tools_by_client([], {}) == {}


def test_the_list_gives_each_client_its_unreviewed_count_zero_when_none_and_unknown_when_unreadable(monkeypatch):
    async def stale(_db, _ids):
        return {}

    monkeypatch.setattr(mssp, "_stale_counts", stale)
    fail = {"on": False}

    async def counts(_db, _owner, ids):
        if fail["on"]:
            raise RuntimeError("remote tool tables unreadable")
        return {ids[0]: 3}

    monkeypatch.setattr(mssp, "_unreviewed_remote_tools", counts)

    async def body(s):
        parent = await make(s, "Parent")
        await make(s, "Acme", parent.id)
        await make(s, "Birch", parent.id)
        await s.commit()
        user = SimpleNamespace(tenant_id=parent.id)
        good = await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=user)
        fail["on"] = True
        bad = await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=user)
        return good, bad

    good, bad = run(body)
    assert sorted(r.unreviewed_remote_tools for r in good) == [0, 3]
    assert [r.unreviewed_remote_tools for r in bad] == [None, None]


# ---- health trend -------------------------------------------------------------------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402


def snap(tenant, days_ago, score, now):
    return MSSPTenantMetrics(id=uuid.uuid4(), tenant_id=tenant, snapshot_at=now - timedelta(days=days_ago), health_score=score)


def test_the_trend_is_each_clients_scores_from_the_last_two_weeks_oldest_first_without_gaps_or_old_or_other_clients():
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)

    async def body(s):
        parent = await make(s, "Parent")
        acme, birch = await make(s, "Acme", parent.id), await make(s, "Birch", parent.id)
        other = await make(s, "Other")
        s.add_all(
            [
                snap(acme.id, 1, 90.0, now),
                snap(acme.id, 5, 70.0, now),
                snap(acme.id, 3, None, now),
                snap(acme.id, 20, 10.0, now),
                snap(birch.id, 2, 55.0, now),
                snap(other.id, 1, 99.0, now),
            ]
        )
        await s.commit()
        got = await mssp._health_trend(s, [acme.id, birch.id], now)
        return got[acme.id], got[birch.id], other.id in got, await mssp._health_trend(s, [], now)

    acme, birch, other_in, none = run(body)
    assert acme == [70.0, 90.0], "oldest first; the empty score and the 20-day-old one are left out"
    assert birch == [55.0] and other_in is False and none == {}


def test_the_list_gives_each_client_its_trend_empty_when_none_and_unknown_when_unreadable(monkeypatch):
    async def stale(_db, _ids):
        return {}

    async def unreviewed(_db, _owner, _ids):
        return {}

    monkeypatch.setattr(mssp, "_stale_counts", stale)
    monkeypatch.setattr(mssp, "_unreviewed_remote_tools", unreviewed)
    fail = {"on": False}
    real = mssp._health_trend

    async def trend(db, ids, now=None):
        if fail["on"]:
            raise RuntimeError("metrics unreadable")
        return await real(db, ids, now)

    monkeypatch.setattr(mssp, "_health_trend", trend)

    async def body(s):
        parent = await make(s, "Parent")
        acme = await make(s, "Acme", parent.id)
        await make(s, "Quiet", parent.id)
        s.add_all([snap(acme.id, 1, 80.0, datetime.now(UTC)), snap(acme.id, 2, 60.0, datetime.now(UTC))])
        await s.commit()
        user = SimpleNamespace(tenant_id=parent.id)
        good = await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=user)
        fail["on"] = True
        bad = await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=user)
        return good, bad

    good, bad = run(body)
    assert {r.name: r.health_trend for r in good} == {"Acme": [60.0, 80.0], "Quiet": []}
    assert [r.health_trend for r in bad] == [None, None]
