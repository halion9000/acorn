"""Hand merges and "not the same person" decisions, against a REAL Postgres as the restricted application role.

The table keeps each pair sorted (``address_a < address_b``) and the code sorts with Python's comparison. The database's own text comparison (en_US and similar) ignores punctuation at first, so it orders some
pairs the other way round ("ab@x.com" sorts BEFORE "a@x.com" there, after it in Python): with the check using the database's order, saving such a pair failed with a constraint error and the button gave a 500.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid

import pytest
from app.api.v1.endpoints.identity_merges import ordered, record
from app.db.rls import set_rls_context
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

# Pairs whose order differs between Python and a punctuation-ignoring database collation.
PAIRS = [
    ("a@x.com", "ab@x.com"),
    ("ab@x.com", "ab@x-y.com"),
    ("a.b@x.com", "a1@x.com"),
    ("a.b@x.com", "aa@x.com"),
    ("a@x.com", "A@x.com"),
]


@pytest.fixture
async def tenant():
    tid = uuid.uuid4()
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
                {"i": tid, "n": f"merges-{tid.hex[:8]}", "s": f"merges-{tid.hex[:8]}"},
            )
        yield tid
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from identity_merges where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await owner.dispose()


async def save(tid, a, b, kind):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            await record(db, client=tid, a=a, b=b, kind=kind, actor=None)
            await db.commit()
    finally:
        await engine.dispose()


async def stored(tid):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            rows = (await db.execute(text("select address_a, address_b, kind from identity_merges where tenant_id = :t"), {"t": tid})).all()
            return {(r[0], r[1]): r[2] for r in rows}
    finally:
        await engine.dispose()


@pytest.mark.parametrize("a,b", PAIRS)
async def test_a_pair_is_saved_whichever_way_round_it_is_named(tenant, a, b):
    await save(tenant, a, b, "merge")
    await save(tenant, b, a, "merge")  # the same decision named the other way round is the same row
    assert await stored(tenant) == {ordered(a, b): "merge"}


async def test_the_opposite_decision_replaces_the_first_for_such_a_pair(tenant):
    a, b = PAIRS[0]
    await save(tenant, a, b, "merge")
    await save(tenant, b, a, "separate")
    assert await stored(tenant) == {ordered(a, b): "separate"}
