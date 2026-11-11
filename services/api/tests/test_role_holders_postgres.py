"""Who holds a role now, on a REAL Postgres: only this organization's own users who hold THIS role, the longest holder first, and a role that is not this tenant's is a 404.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.rbac import role_holders
from app.services import role_history as rh
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
needs_pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def test_holders_are_shaped_and_sorted_longest_first_then_by_name():
    at = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
    out = rh.holders(
        [
            {"user_id": "u3", "username": "", "account_name": "", "email": "zed@x.test", "is_active": True, "assigned_at": at},
            {
                "user_id": "u1",
                "username": "Bea",
                "account_name": "bea",
                "email": "bea@x.test",
                "is_active": False,
                "assigned_at": at - timedelta(days=30),
            },
            {"user_id": "u2", "username": "", "account_name": "amy", "email": None, "is_active": True, "assigned_at": at},
            {"user_id": "u4", "username": None, "account_name": None, "email": None, "is_active": None, "assigned_at": None},
        ]
    )
    assert [h["name"] for h in out] == ["Bea", "amy", "zed@x.test", "Unknown user"], "longest first, the same day by name, no date last"
    assert out[0] == {
        "user_id": "u1",
        "name": "Bea",
        "email": "bea@x.test",
        "since": (at - timedelta(days=30)).isoformat(),
        "active": False,
    }
    assert out[1]["email"] is None and out[1]["active"] is True
    assert out[3]["since"] is None and out[3]["active"] is True, "an account with no flag is not called inactive"
    assert rh.holders([]) == []


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    mine, other = uuid.uuid4(), uuid.uuid4()
    role_a, role_b, foreign_role = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    users = {k: uuid.uuid4() for k in ("old", "new", "other_role", "stranger")}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (mine, other):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"rhold-{t.hex[:10]}"})
        for rid, tid, name in ((role_a, mine, "Analyst"), (role_b, mine, "Viewer"), (foreign_role, other, "Elsewhere")):
            await s.execute(
                text("insert into roles (id, tenant_id, name, is_system, hidden_nav) values (:i, :t, :n, false, '[]'::jsonb)"),
                {"i": rid, "t": tid, "n": name},
            )
        for key, uid in users.items():
            tag = uid.hex[:10]
            await s.execute(
                text(
                    "insert into users (id, tenant_id, email, username, account_name, hashed_password, role, is_active) "
                    "values (:i, :t, :e, :u, :a, 'x', 'analyst', :act)"
                ),
                {
                    "i": uid,
                    "t": other if key == "stranger" else mine,
                    "e": f"{key}-{tag}@x.test",
                    "u": key,
                    "a": f"h{tag}",
                    "act": key != "old",
                },
            )

        async def hold(user_key, role, days_ago):
            await s.execute(
                text("insert into user_roles (user_id, role_id, assigned_at) values (:u, :r, :w)"),
                {"u": users[user_key], "r": role, "w": NOW - timedelta(days=days_ago)},
            )

        await hold("new", role_a, 2)
        await hold("old", role_a, 90)
        await hold("other_role", role_b, 5)
        await hold("stranger", role_a, 400)  # a user of another tenant must never be listed, even holding this role id
        await s.commit()
        s.info.update(mine=mine, other=other, role_a=role_a, role_b=role_b, foreign=foreign_role)
        yield s
        await off(s)
        await s.execute(text("delete from user_roles where user_id = any(cast(:u as uuid[]))"), {"u": [str(u) for u in users.values()]})
        await s.execute(text("delete from users where id = any(cast(:u as uuid[]))"), {"u": [str(u) for u in users.values()]})
        await s.execute(text("delete from roles where tenant_id in (:a, :b)"), {"a": mine, "b": other})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await s.commit()
    await engine.dispose()


def user(tenant):
    return SimpleNamespace(tenant_id=tenant, user_id=None, email="hal@example.com")


@needs_pg
@pytest.mark.asyncio
async def test_only_this_tenants_holders_of_this_role_longest_first(world):
    s = world
    await off(s)
    out = await role_holders(s.info["role_a"], user(s.info["mine"]), s)
    assert [h.name for h in out] == ["old", "new"], "not the holder of another role, not another tenant's user"
    assert out[0].active is False and out[1].active is True
    assert out[0].since is not None and out[0].since < out[1].since


@needs_pg
@pytest.mark.asyncio
async def test_a_role_that_is_not_this_tenants_is_a_404(world):
    s = world
    await off(s)
    with pytest.raises(HTTPException) as caught:
        await role_holders(s.info["foreign"], user(s.info["mine"]), s)
    assert caught.value.status_code == 404
