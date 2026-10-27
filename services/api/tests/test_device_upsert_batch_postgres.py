"""A batch of device reports applied with the client's devices read once (``preload_known``) leaves exactly what the same reports leave when each is applied on its own, against a REAL Postgres.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database). The sequences include the awkward cases: a serial that joins two tools, a source that moves to another device (the device it left
is removed), a junk serial, a serial that arrives later for a device that had none, and the same tool id twice in one batch.
"""

import os
import uuid

import pytest
from app.db.rls import set_rls_context
from app.services.device_upsert import DeviceReport, preload_known, upsert_device
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def tenants():
    tag = uuid.uuid4().hex[:10]
    ids = {"single": uuid.uuid4(), "batch": uuid.uuid4()}
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                await conn.execute(text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ub-{key}-{tag}", "s": f"ub-{key}-{tag}"})
        yield ids, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await engine.dispose()


def r(vendor, ext, host, serial=None, **kw):
    return DeviceReport(vendor, ext, host, serial=serial, **kw)


async def apply(engine, tid, batches, batched):
    """Each batch is one report call: either every report on its own, or the whole batch with the client's devices read once first."""
    for reports in batches:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            known = await preload_known(db, tid, reports) if batched else None
            for rep in reports:
                await upsert_device(db, tid, rep, known) if batched else await upsert_device(db, tid, rep)
            await db.commit()


async def state(engine, tid):
    """The devices as (serial, the sources it holds), without ids or times, so two tenants can be compared."""
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        rows = (
            await conn.execute(
                text(
                    "select d.serial_number, d.hostname, d.os, coalesce(array_agg(s.vendor || ':' || s.external_id || ':' || coalesce(s.name, '') order by s.vendor, s.external_id) "
                    "filter (where s.id is not null), '{}') from devices d left join device_sources s on s.device_id = d.id where d.tenant_id = :t group by d.id"
                ),
                {"t": tid},
            )
        ).all()
    return sorted((str(a), str(b), str(c), tuple(x)) for a, b, c, x in rows)


SEQUENCES = {
    "serial joins two tools, then an update": [
        [r("ninjaone", "n1", "PC-1", "SERIAL-ONE", os="Windows 11"), r("huntress", "h1", "pc-1", "serial-one"), r("threatmate", "t1", "PC-2")],
        [r("ninjaone", "n1", "PC-1 renamed", "SERIAL-ONE"), r("addigy", "a1", "MAC-1", "SERIAL-MAC"), r("ninjaone", "n3", "MAC-1b", "serial-mac")],
    ],
    "a source moves to another device and the one it left is removed": [
        [r("ninjaone", "n1", "PC-1", "SERIAL-ONE"), r("ninjaone", "n2", "PC-2")],
        [r("ninjaone", "n2", "PC-2", "SERIAL-ONE")],
    ],
    "a junk serial counts as none, and a serial that arrives later is kept": [
        [r("ninjaone", "n1", "PC-1", "0"), r("huntress", "h1", "PC-1", "To Be Filled By O.E.M."), r("threatmate", "t1", "PC-9")],
        [r("threatmate", "t1", "PC-9", "REAL-SERIAL-9"), r("ninjaone", "n7", "OTHER", "real-serial-9")],
    ],
    "the same tool id twice in one batch": [
        [r("ninjaone", "n1", "FIRST-NAME", "SERIAL-ONE"), r("ninjaone", "n1", "SECOND-NAME", "SERIAL-ONE"), r("ninjaone", "n5", "PC-5"), r("ninjaone", "n5", "PC-5", "SERIAL-FIVE")],
    ],
    "a tool now reports a different serial under the same id": [
        [r("ninjaone", "n1", "PC-1", "SERIAL-ONE"), r("huntress", "h1", "PC-1", "SERIAL-ONE")],
        [r("ninjaone", "n1", "PC-1", "SERIAL-TWO"), r("huntress", "h1", "PC-1", "SERIAL-TWO")],
    ],
    "many devices and a repeat batch": [
        [r("ninjaone", f"n{i}", f"PC-{i}", f"SERIAL-{i % 7}") for i in range(30)],
        [r("huntress", f"h{i}", f"PC-{i}", f"serial-{i % 7}") for i in range(30)] + [r("ninjaone", f"n{i}", f"PC-{i}", f"SERIAL-{i % 7}") for i in range(30)],
    ],
}


@pytest.mark.parametrize("name", sorted(SEQUENCES))
async def test_a_batch_leaves_exactly_what_the_reports_leave_one_at_a_time(tenants, name):
    ids, engine = tenants
    await apply(engine, ids["single"], SEQUENCES[name], batched=False)
    await apply(engine, ids["batch"], SEQUENCES[name], batched=True)
    one_by_one = await state(engine, ids["single"])
    in_batches = await state(engine, ids["batch"])
    assert one_by_one, "the sequence made some devices"
    assert in_batches == one_by_one


async def test_the_batch_asks_the_database_far_fewer_questions(tenants):
    from sqlalchemy import event

    ids, engine = tenants
    reports = [r("ninjaone", f"n{i}", f"PC-{i}", f"SERIAL-{i}") for i in range(40)]
    await apply(engine, ids["single"], [reports], batched=False)
    await apply(engine, ids["batch"], [reports], batched=True)  # the devices exist now; a second pass is what a sync does all day
    counts = {}
    for key, batched in (("single", False), ("batch", True)):
        selects: list[str] = []

        def count(conn, cursor, statement, parameters, context, executemany, _s=selects):  # noqa: ANN001
            if statement.lstrip().upper().startswith("SELECT"):
                _s.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            await apply(engine, ids[key], [reports], batched=batched)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)
        counts[key] = len(selects)
    assert counts["batch"] < counts["single"] / 3, counts
