"""The managed-clients list's connector counts against a REAL Postgres as the restricted application role (row-level security on).

The counts read every client's connectors in ONE query inside the cross-tenant block. The SQLite test replaces that block with a no-op, so it cannot show that the policy lets an owner's session read its clients'
connectors, nor that another organization's connectors stay out of the numbers. This runs the list's own function as ``aisoc_app`` with the session pinned to the owner, the way a request is.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import mssp
from app.db import rls_hook  # noqa: F401  (installs the listener that makes a tagged session work)
from app.db.rls_sessions import mark_platform, mark_tenant
from app.models.connector import Connector
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]


def connector(tenant_id, health, enabled=True):
    return Connector(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=uuid.uuid4().hex[:8],
        connector_type="cipp",
        category="identity",
        is_enabled=enabled,
        health_status=health,
    )


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("owner", "acme", "birch", "quiet", "other", "theirs")}
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = {"acme": "owner", "birch": "owner", "quiet": "owner", "theirs": "other"}.get(key)
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {
                        "i": tid,
                        "n": f"{key}-{tag}",
                        "s": f"{key}-{tag}",
                        "p": ids[parent] if parent else None,
                        "r": "child" if parent else "parent",
                    },
                )
        async with async_sessionmaker(owner, expire_on_commit=False)() as db:
            mark_platform(db)
            db.add_all(
                [
                    connector(ids["acme"], "healthy"),
                    connector(ids["acme"], "healthy"),
                    connector(ids["acme"], "unhealthy"),
                    connector(ids["acme"], "degraded"),
                    connector(ids["acme"], "unhealthy", enabled=False),
                    connector(ids["birch"], "unknown"),
                    connector(ids["birch"], "healthy"),
                    connector(ids["theirs"], "unhealthy"),
                ]
            )
            await db.commit()
        yield ids, tag
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            everyone = [str(x) for x in ids.values()]
            await conn.execute(text("delete from connectors where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(
                text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": everyone}
            )
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": everyone})
        await owner.dispose()


async def list_as(owner_id):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            mark_tenant(db, owner_id)
            return await mssp.list_managed_tenants(include_hidden=False, db=db, current_user=SimpleNamespace(tenant_id=owner_id))
    finally:
        await engine.dispose()


async def test_each_client_gets_its_enabled_and_failing_counts_and_nothing_of_another_organization(world):
    ids, tag = world
    rows = await list_as(ids["owner"])
    got = {r.name.removesuffix(f"-{tag}"): (r.connectors_enabled, r.connectors_unhealthy) for r in rows if r.name.endswith(f"-{tag}")}
    assert got == {
        "acme": (4, 2),
        "birch": (2, 0),
        "quiet": (0, 0),
    }, "a switched-off connector is not counted, a client with none is 0 and 0, and the other organization's client is not listed"


async def test_the_other_organization_sees_only_its_own_client_and_its_numbers(world):
    ids, tag = world
    rows = await list_as(ids["other"])
    got = {r.name.removesuffix(f"-{tag}"): (r.connectors_enabled, r.connectors_unhealthy) for r in rows if r.name.endswith(f"-{tag}")}
    assert got == {"theirs": (1, 1)}
