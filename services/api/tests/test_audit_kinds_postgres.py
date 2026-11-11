"""The kinds of event in the audit trail on a REAL Postgres: the action prefixes this tenant's trail holds, most frequent first, with counts; another tenant's entries and an action with no colon are not counted.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.audit import audit_kinds
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


async def add(s, tenant, action, times=1):
    for _ in range(times):
        await s.execute(
            text(
                "insert into audit_log (id, tenant_id, actor_email, action, resource, resource_id, created_at) values (gen_random_uuid(), :t, 'a@x.test', :a, 'x', 'y', now())"
            ),
            {"t": tenant, "a": action},
        )


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    mine, other = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (mine, other):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"ak-{t.hex[:10]}"})
        await add(s, mine, "alerts:bulk_close", 5)
        await add(s, mine, "alerts:bulk_assign", 2)
        await add(s, mine, "role:created", 3)
        await add(s, mine, "tenant:renamed", 1)
        await add(s, mine, "plain_action_without_colon", 4)
        await add(s, other, "secret:elsewhere", 9)
        await s.commit()
        s.info.update(mine=mine)
        yield s
        await off(s)
        await s.execute(text("set local session_replication_role = replica"))  # audit rows refuse deletion; for this clean-up only
        await s.execute(text("delete from audit_log where tenant_id in (:a, :b)"), {"a": mine, "b": other})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await s.commit()
    await engine.dispose()


async def test_the_kinds_are_this_tenants_action_prefixes_most_frequent_first(world):
    s = world
    await off(s)
    out = await audit_kinds(SimpleNamespace(tenant_id=s.info["mine"]), s)
    assert [(k.prefix, k.count) for k in out.kinds] == [("alerts:", 7), ("role:", 3), ("tenant:", 1)]
