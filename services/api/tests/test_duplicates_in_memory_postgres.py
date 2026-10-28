"""The duplicates list is worked out from the devices already loaded and gives exactly what the per-client queries gave, against a REAL Postgres.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database). The cases include a same-name pair, two different serials, a hardware unit beside an agent's machine, a made-up Auvik name matched
by address, a machine only ScreenConnect lists, and a pair a person said is different.
"""

import os
import uuid
from types import SimpleNamespace as NS

import pytest
from app.api.v1.endpoints import devices as ep
from app.db.rls import set_rls_context
from app.services.device_merge import dismiss_pair
from app.services.device_upsert import DeviceReport, possible_duplicates, upsert_device
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    w = {k: uuid.uuid4() for k in ("parent", "acme")}
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    ep.forget_loaded()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key in ("parent", "acme"):
                parent = w["parent"] if key == "acme" else None
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": w[key], "n": f"dm-{key}-{tag}", "s": f"dm-{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
        yield w, engine
    finally:
        ep.forget_loaded()
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            t = [str(w["parent"]), str(w["acme"])]
            for table in ("device_merge_dismissals", "device_sources", "devices"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": t})
            await conn.execute(text("delete from tenants where id = :c"), {"c": w["acme"]})
            await conn.execute(text("delete from tenants where id = :p"), {"p": w["parent"]})
        await engine.dispose()


async def session(engine, tenant):
    db = async_sessionmaker(engine, expire_on_commit=False)()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    await set_rls_context(db, tenant)
    return db


async def fill(engine, tid):
    reports = [
        DeviceReport("ninjaone", "n1", "FRONT-DESK-7"),
        DeviceReport("huntress", "h1", "front-desk-7"),  # same name, other tool: a pair
        DeviceReport("ninjaone", "n2", "PC-A", serial="SERIAL-AAAA"),
        DeviceReport("huntress", "h2", "PC-A", serial="SERIAL-BBBB"),  # same name, different serials: not a pair
        DeviceReport("auvik", "a1", "Device@10.0.0.9", ip_addresses=["10.0.0.9"], manufacturer="Dell"),
        DeviceReport("ninjaone", "n3", "OFFICE-PC-3", ip_addresses=["10.0.0.9"], manufacturer="Dell Inc."),  # matched by address and maker
        DeviceReport("unifi", "u1", "AP-HQ", details={"mac": "AABBCCDDEE01"}),
        DeviceReport("ninjaone", "n4", "AP-HQ"),  # a hardware unit beside an agent's machine: not a pair
        DeviceReport("screenconnect", "s1", "KIOSK-1"),
        DeviceReport("screenconnect", "s2", "KIOSK-1"),  # ScreenConnect only, no serial: left out
        DeviceReport("ninjaone", "n5", "DISMISSED-PC"),
        DeviceReport("threatmate", "t5", "DISMISSED-PC"),  # a pair a person dismissed
        DeviceReport("ninjaone", "n6", "LONELY-PC"),
    ]
    db = await session(engine, tid)
    for r in reports:
        await upsert_device(db, tid, r)
    await db.commit()
    await db.close()


async def dismiss_the_dismissed(engine, tid):
    db = await session(engine, tid)
    ids = [
        r[0]
        for r in (
            await db.execute(text("select id from devices where tenant_id = :t and upper(hostname) = 'DISMISSED-PC'"), {"t": tid})
        ).all()
    ]
    assert len(ids) == 2
    await dismiss_pair(db, tid, ids[0], ids[1])
    await db.commit()
    await db.close()


def as_pairs(items):
    return sorted(tuple(sorted((str(i.a.id), str(i.b.id)))) for i in items)


async def test_the_list_from_memory_is_exactly_what_the_per_client_queries_gave(world):
    w, engine = world
    await fill(engine, w["acme"])
    await dismiss_the_dismissed(engine, w["acme"])

    old_db = await session(engine, w["acme"])
    old = sorted(tuple(sorted((str(a), str(b)))) for a, b in await possible_duplicates(old_db, w["acme"]))
    await old_db.close()
    assert len(old) == 2, "the same-name pair and the address pair; the others are left out"

    db = await session(engine, w["parent"])
    out = await ep.list_duplicates(current_user=NS(tenant_id=w["parent"]), db=db, client_id=None)
    await db.close()
    assert as_pairs(out.items) == old
    assert all((i.a.client_name or "").startswith("dm-acme-") for i in out.items), "each pair is named for its client"


async def test_a_dismissal_made_after_the_list_was_loaded_applies_once_the_person_forgets_the_cache(world):
    w, engine = world
    await fill(engine, w["acme"])
    db = await session(engine, w["parent"])
    before = await ep.list_duplicates(current_user=NS(tenant_id=w["parent"]), db=db, client_id=None)
    await db.close()
    assert len(before.items) == 3, "the dismissed pair is still offered before it is dismissed"
    await dismiss_the_dismissed(engine, w["acme"])
    ep.forget_loaded()
    db = await session(engine, w["parent"])
    after = await ep.list_duplicates(current_user=NS(tenant_id=w["parent"]), db=db, client_id=None)
    await db.close()
    assert len(after.items) == 2
