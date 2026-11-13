"""Two lines that are one machine under different serial numbers can be merged on a person's word, and the merge holds, against a REAL Postgres as the restricted role.

An Azure or Hyper-V virtual machine carries one serial in NinjaOne (the Hyper-V one) and another in Huntress, ScreenConnect and ThreatMate (the one the guest operating system reports): one
machine, two lines, and the refusal "different serial numbers, so different machines" is right for two PCs and wrong here. A person can say "same machine". The merge then has to HOLD: the
removed line's serial is kept on the device as another serial of the same machine, so the next report from a tool that gives that serial does not split the line off again (that is what
upsert_device does when a known tool record reports a serial that is not the device's). Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, migrated database).
"""

import os
import uuid

import pytest
from app.api.v1.endpoints import devices as devices_endpoints
from app.api.v1.endpoints.devices import MergeIn, merge_duplicate
from app.db.rls import set_rls_context
from app.services.device_merge import DeviceMergeError, merge_devices, undo_merge
from app.services.device_upsert import DeviceReport, upsert_device
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)

HYPERV = "5544-1934-1387-0849-7647-8741-99"  # what NinjaOne reports for the VM
GUEST = "0000-0011-8716-1173-5020-6851-43"  # what Huntress, ScreenConnect and ThreatMate report for the same VM


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {"parent": uuid.uuid4(), "acme": uuid.uuid4()}
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {
                        "i": tid,
                        "n": f"{key}-{tag}",
                        "s": f"{key}-{tag}",
                        "p": ids["parent"] if key == "acme" else None,
                        "r": "child" if key == "acme" else "parent",
                    },
                )
        yield ids
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await owner.dispose()


async def run(tenant_id, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant_id)
            result = await work(db)
            await db.commit()
            return result
    finally:
        await engine.dispose()


async def rows(tenant_id, sql):
    return await run(tenant_id, lambda db: db.execute(text(sql), {"t": tenant_id}))


async def devices_of(tenant_id):
    result = await rows(
        tenant_id, "select hostname, serial_number, alt_serials from devices where tenant_id = :t order by hostname, serial_number"
    )
    return [tuple(r) for r in result.all()]


async def sources_of(tenant_id):
    result = await rows(tenant_id, "select vendor, device_id from device_sources where tenant_id = :t order by vendor")
    return [(r[0], r[1]) for r in result.all()]


async def the_vm_as_two_lines(t):
    ninja = await run(t, lambda db: upsert_device(db, t, DeviceReport("ninjaone", "n-1", "AZ-DC", serial=HYPERV)))
    guest = await run(t, lambda db: upsert_device(db, t, DeviceReport("huntress", "h-1", "AZ-DC", serial=GUEST)))
    await run(t, lambda db: upsert_device(db, t, DeviceReport("screenconnect", "s-1", "AZ-DC", serial=GUEST)))
    return ninja, guest


async def test_without_the_persons_word_different_serials_are_still_refused(world):
    t = world["acme"]
    ninja, guest = await the_vm_as_two_lines(t)
    with pytest.raises(DeviceMergeError, match="different serial"):
        await run(t, lambda db: merge_devices(db, t, ninja, guest))
    assert len(await devices_of(t)) == 2


async def test_saying_same_machine_merges_them_and_the_merge_holds_when_the_tools_report_again(world):
    t = world["acme"]
    ninja, guest = await the_vm_as_two_lines(t)
    await run(t, lambda db: merge_devices(db, t, ninja, guest, same_machine=True))
    assert await devices_of(t) == [
        ("AZ-DC", HYPERV, [GUEST])
    ], "one device, NinjaOne's serial, the other kept as another serial of the machine"
    assert {d for _v, d in await sources_of(t)} == {ninja}
    # The tools report again, as they do every hour: nothing splits off, and a tool that never reported before and gives the other serial joins the same device.
    await run(t, lambda db: upsert_device(db, t, DeviceReport("huntress", "h-1", "AZ-DC", serial=GUEST)))
    await run(t, lambda db: upsert_device(db, t, DeviceReport("ninjaone", "n-1", "AZ-DC", serial=HYPERV)))
    await run(t, lambda db: upsert_device(db, t, DeviceReport("threatmate", "t-1", "AZ-DC", serial=GUEST)))
    assert len(await devices_of(t)) == 1
    assert sorted(v for v, _d in await sources_of(t)) == ["huntress", "ninjaone", "screenconnect", "threatmate"]
    assert {d for _v, d in await sources_of(t)} == {ninja}


async def test_it_does_not_hold_without_the_other_serial_being_kept(world):
    # The reason the other serial is stored: a merge on a person's word alone would split again at the next report.
    t = world["acme"]
    ninja, guest = await the_vm_as_two_lines(t)
    await run(t, lambda db: merge_devices(db, t, ninja, guest, same_machine=True))
    await rows(t, "update devices set alt_serials = '{}' where tenant_id = :t")
    await run(t, lambda db: upsert_device(db, t, DeviceReport("huntress", "h-1", "AZ-DC", serial=GUEST)))
    assert len(await devices_of(t)) == 2


async def test_undo_gives_the_removed_line_and_its_serial_back_and_takes_the_other_serial_off(world):
    t = world["acme"]
    ninja, guest = await the_vm_as_two_lines(t)
    await run(t, lambda db: merge_devices(db, t, ninja, guest, same_machine=True))
    merge_id = (await rows(t, "select id from device_merge_log where tenant_id = :t")).scalar_one()
    await run(t, lambda db: undo_merge(db, t, merge_id))
    assert await devices_of(t) == [("AZ-DC", GUEST, []), ("AZ-DC", HYPERV, [])]


async def test_the_route_answers_409_for_different_serials_and_merges_when_the_person_says_same_machine(world):
    t, p = world["acme"], world["parent"]
    ninja, guest = await the_vm_as_two_lines(t)
    user = type("U", (), {"tenant_id": p, "user_id": None})()
    devices_endpoints.forget_loaded()
    with pytest.raises(HTTPException) as refused:
        await run(p, lambda db: merge_duplicate(MergeIn(keep=ninja, remove=guest), user, db))
    assert refused.value.status_code == 409 and "different serial numbers" in str(refused.value.detail)
    merged = await run(p, lambda db: merge_duplicate(MergeIn(keep=ninja, remove=guest, same_machine=True), user, db))
    assert merged.id == ninja and sorted(s.vendor for s in merged.sources) == ["huntress", "ninjaone", "screenconnect"]
