"""Shared saved views on a REAL Postgres: a view its owner shares is listed for others in the same tenant, applied by them but never changed or deleted by them, a default stays personal, and nobody sees
another tenant's views. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.saved_views import (
    CreateSavedViewRequest,
    UpdateSavedViewRequest,
    create_saved_view,
    delete_saved_view,
    list_saved_views,
    update_saved_view,
)
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


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant, other_tenant = uuid.uuid4(), uuid.uuid4()
    ann, bob, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (tenant, other_tenant):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"sv-{t.hex[:10]}"})
        for uid, tid, name in ((ann, tenant, "ann"), (bob, tenant, "bob"), (stranger, other_tenant, "str")):
            await s.execute(
                text("insert into users (id, tenant_id, email, username, hashed_password, account_name) values (:i, :t, :e, :u, 'x', :a)"),
                {"i": uid, "t": tid, "e": f"{name}-{uid.hex[:6]}@example.com", "u": f"{name}-{uid.hex[:6]}", "a": f"{name}-{uid.hex[:6]}"},
            )
        await s.commit()
        s.info.update(users={n: SimpleNamespace(tenant_id=t, user_id=u, email=f"{n}@x") for n, t, u in (("ann", tenant, ann), ("bob", tenant, bob), ("stranger", other_tenant, stranger))})
        yield s
        await off(s)
        await s.execute(text("delete from saved_views where tenant_id in (:a, :b)"), {"a": tenant, "b": other_tenant})
        await s.execute(text("delete from users where id in (:a, :b, :c)"), {"a": ann, "b": bob, "c": stranger})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": tenant, "b": other_tenant})
        await s.commit()
    await engine.dispose()


async def make(s, who, name, shared=False, is_default=False):
    await off(s)
    return await create_saved_view(CreateSavedViewRequest(view_type="devices", name=name, filters={"os": "mac"}, shared=shared, is_default=is_default), s.info["users"][who], s)


async def names(s, who):
    await off(s)
    return [(v.name, v.mine, v.shared, v.is_default) for v in await list_saved_views(s.info["users"][who], s, "devices")]


async def test_a_shared_view_is_listed_for_others_in_the_tenant_but_a_private_one_and_another_tenants_are_not(world):
    s = world
    await make(s, "ann", "Ann private")
    await make(s, "ann", "Ann shared", shared=True)
    await make(s, "bob", "Bob own")
    await make(s, "stranger", "Elsewhere shared", shared=True)
    assert await names(s, "bob") == [("Bob own", True, False, False), ("Ann shared", False, True, False)], "mine first, then what others shared; Ann's private view and the other tenant's are not here"
    assert sorted(n for n, *_ in await names(s, "ann")) == ["Ann private", "Ann shared"]
    assert [n for n, *_ in await names(s, "stranger")] == ["Elsewhere shared"]


async def test_a_shared_default_is_only_the_owners_default_and_comes_first_only_for_the_owner(world):
    s = world
    await make(s, "ann", "Ann default", shared=True, is_default=True)
    await make(s, "bob", "Bob own")
    assert await names(s, "ann") == [("Ann default", True, True, True)]
    assert await names(s, "bob") == [("Bob own", True, False, False), ("Ann default", False, True, False)], "to Bob it is not a default"


async def test_only_the_owner_can_change_share_or_delete_a_view(world):
    s = world
    mine = await make(s, "ann", "Ann view")
    await off(s)
    shared = await update_saved_view(mine.id, UpdateSavedViewRequest(shared=True), s.info["users"]["ann"], s)
    assert shared.shared is True and shared.mine is True
    assert [n for n, *_ in await names(s, "bob")] == ["Ann view"]
    for action in (
        lambda: update_saved_view(mine.id, UpdateSavedViewRequest(name="Hijacked"), s.info["users"]["bob"], s),
        lambda: update_saved_view(mine.id, UpdateSavedViewRequest(shared=False), s.info["users"]["bob"], s),
        lambda: delete_saved_view(mine.id, s.info["users"]["bob"], s),
    ):
        await off(s)
        with pytest.raises(HTTPException) as err:
            await action()
        assert err.value.status_code == 404
    await off(s)
    back = await update_saved_view(mine.id, UpdateSavedViewRequest(shared=False), s.info["users"]["ann"], s)
    assert back.shared is False
    assert await names(s, "bob") == []
