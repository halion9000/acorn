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
