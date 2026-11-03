"""The managed-clients list says how many connectors each client has switched on and how many of those are failing; when that cannot be read it says so (None), never zero."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import mssp
from app.db.database import Base
from app.models.client_alias import ClientAlias
from app.models.connector import Connector
from app.models.mssp import MSSPTenantMetrics
from app.models.tenant import Tenant
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, MSSPTenantMetrics, ClientAlias, Connector)]


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    import app.db.rls_scope as scope

    @contextlib.asynccontextmanager
    async def no_rls(_db):
        yield

    monkeypatch.setattr(scope, "cross_tenant_reads", no_rls)  # the row-level-security switch is Postgres-only


def run(coro_fn, tables=TABLES):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=tables))
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


def connector(tenant_id, health, enabled=True, name=None):
    return Connector(id=uuid.uuid4(), tenant_id=tenant_id, name=name or uuid.uuid4().hex[:6], connector_type="cipp", category="identity", is_enabled=enabled, health_status=health)


def rows_by_name(rows):
    return {r.name: (r.connectors_enabled, r.connectors_unhealthy) for r in rows}


def test_each_client_gets_its_enabled_and_failing_counts_and_switched_off_connectors_are_not_counted():
    async def body(s):
        parent = await tenant(s, "Parent")
        acme, birch, quiet = await tenant(s, "Acme", parent.id), await tenant(s, "Birch", parent.id), await tenant(s, "Quiet", parent.id)
        other = await tenant(s, "Other MSSP")
        theirs = await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                connector(acme.id, "healthy"), connector(acme.id, "healthy"), connector(acme.id, "unhealthy"), connector(acme.id, "degraded"), connector(acme.id, "unhealthy", enabled=False),
                connector(birch.id, "unknown"), connector(birch.id, "healthy"),
                connector(theirs.id, "unhealthy"),
            ]
        )
        await s.commit()
        return await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=SimpleNamespace(tenant_id=parent.id))

    got = rows_by_name(run(body))
    assert got == {"Acme": (4, 2), "Birch": (2, 0), "Quiet": (0, 0)}  # a client with none is 0 and 0; the other MSSP's client is not in the list


def test_a_connector_read_that_fails_gives_unknown_not_zero_and_the_list_still_loads():
    async def body(s):
        parent = await tenant(s, "Parent")
        await tenant(s, "Acme", parent.id)
        await s.commit()
        return await mssp.list_managed_tenants(include_hidden=False, db=s, current_user=SimpleNamespace(tenant_id=parent.id))

    rows = run(body, tables=[m.__table__ for m in (Tenant, MSSPTenantMetrics, ClientAlias)])  # there is no connectors table to read
    assert [r.name for r in rows] == ["Acme"] and rows_by_name(rows) == {"Acme": (None, None)}
