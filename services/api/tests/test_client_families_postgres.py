"""Client families against a REAL Postgres (opt in with AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import client_families as ep
from app.db.rls import set_rls_context
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    owner_id, a, b, c = (uuid.uuid4() for _ in range(4))
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": owner_id, "n": f"owner-{tag}", "s": f"owner-{tag}"})
            for tid, name in ((a, "NW - North"), (b, "NW - South"), (c, "Other Co")):
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, :n, :s, :p)"), {"i": tid, "n": name, "s": f"{name[:2].lower()}-{tag}-{str(tid)[:4]}", "p": owner_id}
                )
        yield SimpleNamespace(owner=owner_id, a=a, b=b, c=c)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from client_families where tenant_id = :t"), {"t": owner_id})
            await conn.execute(text("delete from tenants where parent_tenant_id = :t"), {"t": owner_id})
            await conn.execute(text("delete from tenants where id = :t"), {"t": owner_id})
        await engine.dispose()


async def run(w, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await work(db)
    finally:
        await engine.dispose()


def user(w):
    return SimpleNamespace(tenant_id=w.owner, user_id=uuid.uuid4())


async def test_a_family_links_clients_renames_and_deletes_without_touching_the_clients(world):
    w = world
    made = await run(w, lambda db: ep.create_family(ep.FamilyIn(name="New Waterloo", client_ids=[w.a, w.b]), user(w), db))
    assert made.name == "New Waterloo" and made.clients == ["NW - North", "NW - South"]
    listed = await run(w, lambda db: ep.list_families(user(w), db))
    assert [f.name for f in listed] == ["New Waterloo"]
    fmap = await run(w, lambda db: ep.load_family_map(db, w.owner))
    assert set(fmap) == {w.a, w.b}

    changed = await run(w, lambda db: ep.change_family(made.id, ep.FamilyPatch(name="NW Group", client_ids=[w.a]), user(w), db))
    assert changed.name == "NW Group" and changed.client_ids == [w.a]

    await run(w, lambda db: ep.delete_family(made.id, user(w), db))
    assert await run(w, lambda db: ep.list_families(user(w), db)) == []
    kids = await run(w, lambda db: ep._clients(db, w.owner))
    assert set(kids) == {w.a, w.b, w.c}, "deleting a family leaves every client in place"


async def test_a_client_cannot_be_in_two_families_and_a_name_cannot_repeat(world):
    w = world
    await run(w, lambda db: ep.create_family(ep.FamilyIn(name="One", client_ids=[w.a]), user(w), db))
    with pytest.raises(HTTPException) as e:
        await run(w, lambda db: ep.create_family(ep.FamilyIn(name="Two", client_ids=[w.a]), user(w), db))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        await run(w, lambda db: ep.create_family(ep.FamilyIn(name="one", client_ids=[]), user(w), db))
    assert e2.value.status_code == 409
    with pytest.raises(HTTPException) as e3:
        await run(w, lambda db: ep.create_family(ep.FamilyIn(name="Three", client_ids=[uuid.uuid4()]), user(w), db))
    assert e3.value.status_code == 400
