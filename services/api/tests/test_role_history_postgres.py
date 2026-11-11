"""A role's recent changes on a REAL Postgres: the last ten audit entries of that role in this tenant, newest first, in plain words; another role's entries and another tenant's are not shown,
and a role that is not this tenant's is a 404. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.rbac import role_history_list
from fastapi import HTTPException
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


async def entry(s, tenant, role, action, changes, minutes_ago):
    await s.execute(
        text(
            "insert into audit_log (id, tenant_id, actor_email, action, resource, resource_id, changes, created_at) "
            "values (gen_random_uuid(), :t, 'boss@example.com', :a, 'role', :r, cast(:c as jsonb), now() - make_interval(mins => :m))"
        ),
        {"t": tenant, "a": action, "r": str(role), "c": json.dumps(changes), "m": minutes_ago},
    )


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    mine, other = uuid.uuid4(), uuid.uuid4()
    role_a, role_b, foreign_role = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (mine, other):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"rh-{t.hex[:10]}"})
        for rid, tid, name in ((role_a, mine, "Analyst"), (role_b, mine, "Viewer"), (foreign_role, other, "Elsewhere")):
            await s.execute(
                text("insert into roles (id, tenant_id, name, is_system, hidden_nav) values (:i, :t, :n, false, '[]'::jsonb)"),
                {"i": rid, "t": tid, "n": name},
            )
        await entry(s, mine, role_a, "role:created", {"name": "Analyst", "permissions": ["alerts:read"]}, 300)
        for i in range(11):
            await entry(
                s,
                mine,
                role_a,
                "role:updated",
                {"name": {"before": "Analyst", "after": "Analyst"}, "permissions_added": [f"p{i}:read"], "permissions_removed": []},
                200 - i,
            )
        await entry(s, mine, role_b, "role:deleted", {}, 1)
        await entry(s, other, role_a, "role:deleted", {}, 1)  # the same id in another tenant's log must not leak
        await s.commit()
        s.info.update(mine=mine, role_a=role_a, role_b=role_b, foreign=foreign_role)
        yield s
        await off(s)
        await s.execute(text("set local session_replication_role = replica"))  # audit rows refuse deletion; for this clean-up only
        await s.execute(text("delete from audit_log where tenant_id in (:a, :b)"), {"a": mine, "b": other})
        await s.execute(text("delete from roles where tenant_id in (:a, :b)"), {"a": mine, "b": other})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await s.commit()
    await engine.dispose()


def user(tenant):
    return SimpleNamespace(tenant_id=tenant, user_id=None, email="hal@example.com")


async def test_the_last_ten_changes_come_newest_first_in_plain_words_and_only_this_roles(world):
    s = world
    await off(s)
    rows = await role_history_list(s.info["role_a"], user(s.info["mine"]), s)
    assert len(rows) == 10, "the two oldest (the creation and p0) are cut by the limit of ten"
    assert all(r.action == "role:updated" and r.by == "boss@example.com" for r in rows)
    assert rows[0].summary == "Gained p10:read." and rows[-1].summary == "Gained p1:read."
    await off(s)
    only_b = await role_history_list(s.info["role_b"], user(s.info["mine"]), s)
    assert [(r.action, r.summary) for r in only_b] == [("role:deleted", "Deleted.")]


async def test_a_role_that_is_not_this_tenants_is_a_404(world):
    s = world
    await off(s)
    with pytest.raises(HTTPException) as caught:
        await role_history_list(s.info["foreign"], user(s.info["mine"]), s)
    assert caught.value.status_code == 404
