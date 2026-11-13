"""A security tool's record of a machine follows the machine to the client the RMM files it under, against a REAL Postgres as the restricted role.

Huntress keeps its own organizations, and they are not always the RMM's: one Huntress organization can hold the machines of several NinjaOne organizations (a hotel group filed per hotel in
NinjaOne and as one in Huntress), or the same client under another name. A Huntress organization maps to ONE client, so its agents landed under that client while NinjaOne's record of the same
machine sat under another: the Devices page then said "not in Huntress" for a machine Huntress protects. Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, migrated database).
"""

import os
import uuid

import pytest
from app.api.v1.endpoints import devices as devices_endpoints
from app.api.v1.endpoints.devices import DeviceIn, DevicesReport, apply_devices, is_missing_from
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.test_devices_endpoints_postgres import list_devices, user

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("parent", "hotel_a", "hotel_b", "group")}
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = None if key == "parent" else ids["parent"]
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            # NinjaOne files each hotel on its own; Huntress has ONE organization for the group, mapped to the group's own client.
            for vendor, vid, child in [
                ("ninjaone", "A", "hotel_a"),
                ("ninjaone", "B", "hotel_b"),
                ("ninjaone", "G", "group"),
                ("huntress", "H", "group"),
                ("huntress", "HA", "hotel_a"),
            ]:
                await conn.execute(
                    text(
                        "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                        "values (:p, :v, :vid, :n, :n, :c, false, 'manual')"
                    ),
                    {"p": ids["parent"], "v": vendor, "vid": vid, "n": child, "c": ids[child]},
                )
        yield ids
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await owner.dispose()


async def as_app(tenant_id, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant_id)
            result = await work(db)
            await db.commit()
            return result
    finally:
        await engine.dispose()


def dev(vendor, vid, ext, host, serial=None):
    return DeviceIn(vendor=vendor, vendor_client_id=vid, external_id=ext, hostname=host, serial=serial)


async def send(world, *items):
    p = world["parent"]
    return await as_app(p, lambda db: apply_devices(db, p, DevicesReport(items=list(items))))


async def held(world, client):
    """What a client holds: {hostname: sorted vendors}, one entry per device."""
    p = world["parent"]
    devices_endpoints.forget_loaded()  # the page keeps a list for some seconds; these tests look again at once
    listing = await as_app(p, lambda db: list_devices(user(p), db, client_id=world[client]))
    return sorted((d.hostname, sorted(s.vendor for s in d.sources)) for d in listing.items), listing.items


async def test_a_huntress_agent_joins_the_machine_under_the_client_ninjaone_files_it_under(world):
    res = await send(
        world,
        dev("ninjaone", "A", "n1", "HOTEL-A-PC1", "SERIAL-A1"),
        dev("ninjaone", "B", "n2", "HOTEL-B-PC1", "SERIAL-B1"),
        dev("huntress", "H", "h1", "hotel-a-pc1", "serial-a1"),
        dev("huntress", "H", "h2", "HOTEL-B-PC1.corp.local", "SERIAL-B1"),
        dev("huntress", "H", "h3", "GROUP-ONLY-PC", "SERIAL-G1"),
    )
    assert (res.accepted, res.followed) == (5, 2)
    a, a_items = await held(world, "hotel_a")
    b, _ = await held(world, "hotel_b")
    g, _ = await held(world, "group")
    assert a == [("HOTEL-A-PC1", ["huntress", "ninjaone"])]
    assert b == [("HOTEL-B-PC1", ["huntress", "ninjaone"])]
    assert g == [("GROUP-ONLY-PC", ["huntress"])]  # NinjaOne does not know this one: it stays where its Huntress organization is mapped
    assert is_missing_from(a_items[0], "huntress") is False


async def test_an_agent_already_stored_under_the_other_client_moves_and_leaves_nothing_behind(world):
    # The state production is in: Huntress's record under the group, NinjaOne's under the hotel, each alone.
    first = await send(world, dev("huntress", "H", "h1", "HOTEL-A-PC1", "SERIAL-A1"))
    assert first.followed == 0
    assert (await held(world, "group"))[0] == [("HOTEL-A-PC1", ["huntress"])]
    await send(world, dev("ninjaone", "A", "n1", "HOTEL-A-PC1", "SERIAL-A1"))
    assert (await held(world, "hotel_a"))[0] == [("HOTEL-A-PC1", ["ninjaone"])]
    # The next Huntress report finds the machine under the hotel and goes there; the record under the group is removed with its device.
    again = await send(world, dev("huntress", "H", "h1", "HOTEL-A-PC1", "SERIAL-A1"))
    assert again.followed == 1
    assert (await held(world, "hotel_a"))[0] == [("HOTEL-A-PC1", ["huntress", "ninjaone"])]
    assert (await held(world, "group"))[0] == []
    # And it stays put on every later report.
    once_more = await send(world, dev("huntress", "H", "h1", "HOTEL-A-PC1", "SERIAL-A1"))
    assert once_more.followed == 1
    assert (await held(world, "hotel_a"))[0] == [("HOTEL-A-PC1", ["huntress", "ninjaone"])]
    assert (await held(world, "group"))[0] == []


async def test_it_follows_only_a_machine_that_is_plainly_the_same_and_in_one_place(world):
    await send(
        world,
        dev("ninjaone", "A", "n1", "HOTEL-A-PC1", "SERIAL-A1"),
        dev("ninjaone", "A", "n2", "FRONTDESK", "SERIAL-SHARED"),
        dev("ninjaone", "B", "n3", "FRONTDESK", "SERIAL-SHARED"),
        dev("ninjaone", "A", "n4", "NOSERIAL-PC"),
    )
    res = await send(
        world,
        dev("huntress", "H", "h1", "SOMETHING-ELSE", "SERIAL-A1"),  # the same serial under another name: not plainly the same machine
        dev("huntress", "H", "h2", "FRONTDESK", "SERIAL-SHARED"),  # NinjaOne has it under two clients: no single place to follow to
        dev("huntress", "H", "h3", "NOSERIAL-PC"),  # no serial to go by
        dev("huntress", "H", "h4", "HOTEL-A-PC1", "To be filled by O.E.M."),  # a placeholder is not a serial
    )
    assert res.followed == 0
    assert sorted(h for h, _v in (await held(world, "group"))[0]) == ["FRONTDESK", "HOTEL-A-PC1", "NOSERIAL-PC", "SOMETHING-ELSE"]
    assert all(v == ["ninjaone"] for _h, v in (await held(world, "hotel_a"))[0])


async def test_the_rmm_record_never_moves_and_an_agent_already_with_its_machine_stays(world):
    # Huntress's organization HA is mapped to hotel A itself; NinjaOne files a machine of the same serial under the group. NinjaOne is what says where a machine belongs, so nothing of
    # NinjaOne's moves; Huntress's record follows NinjaOne's.
    res = await send(world, dev("huntress", "HA", "h1", "ROAMING-PC", "SERIAL-R1"), dev("ninjaone", "G", "n1", "ROAMING-PC", "SERIAL-R1"))
    assert res.followed == 1
    assert (await held(world, "group"))[0] == [("ROAMING-PC", ["huntress", "ninjaone"])]
    assert (await held(world, "hotel_a"))[0] == []
    # Already together: nothing to follow.
    same = await send(
        world, dev("ninjaone", "A", "n9", "HOTEL-A-PC9", "SERIAL-A9"), dev("huntress", "HA", "h9", "HOTEL-A-PC9", "SERIAL-A9")
    )
    assert same.followed == 0
    assert ("HOTEL-A-PC9", ["huntress", "ninjaone"]) in (await held(world, "hotel_a"))[0]


async def as_owner(statement, params):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text(statement), params)).rowcount
    finally:
        await engine.dispose()


async def test_a_record_the_rmm_stopped_reporting_decides_nothing(world):
    # NinjaOne once had the machine under hotel A and no longer reports it there (it was handed to the group, where only Huntress runs on it).
    await send(world, dev("ninjaone", "A", "n1", "MOVED-PC", "SERIAL-M1"))
    aged = await as_owner(
        "update device_sources set last_seen = now() - interval '10 days' where tenant_id = :t and vendor = 'ninjaone' and external_id = 'n1'",
        {"t": world["hotel_a"]},
    )
    assert aged == 1
    res = await send(world, dev("huntress", "H", "h1", "MOVED-PC", "SERIAL-M1"))
    assert res.followed == 0
    assert (await held(world, "group"))[0] == [("MOVED-PC", ["huntress"])]
    assert (await held(world, "hotel_a"))[0] == [("MOVED-PC", ["ninjaone"])]
    # Reported again, it counts again.
    await send(world, dev("ninjaone", "A", "n1", "MOVED-PC", "SERIAL-M1"))
    assert (await send(world, dev("huntress", "H", "h1", "MOVED-PC", "SERIAL-M1"))).followed == 1
    assert (await held(world, "group"))[0] == []


async def test_a_renamed_machine_is_followed_by_the_name_the_rmm_gives_today(world):
    await send(world, dev("ninjaone", "A", "n1", "OLD-NAME", "SERIAL-N1"))
    # The same NinjaOne record, renamed. The device keeps the name it was first seen with; the record carries today's.
    await send(world, dev("ninjaone", "A", "n1", "NEW-NAME", "SERIAL-N1"))
    res = await send(world, dev("huntress", "H", "h1", "NEW-NAME", "SERIAL-N1"), dev("huntress", "H", "h2", "OLD-NAME", "SERIAL-N1"))
    assert res.followed == 1
    a, a_items = await held(world, "hotel_a")
    assert [v for _h, v in a] == [["huntress", "ninjaone"]]
    assert [s.name for s in a_items[0].sources if s.vendor == "huntress"] == ["NEW-NAME"]
    assert (await held(world, "group"))[0] == [("OLD-NAME", ["huntress"])]


async def test_a_hidden_client_never_pulls_a_record_out_of_a_shown_one_and_a_moved_record_says_where_it_came_from(world):
    await send(world, dev("ninjaone", "B", "n1", "TEST-PC", "SERIAL-T1"), dev("ninjaone", "A", "n2", "REAL-PC", "SERIAL-T2"))
    assert await as_owner("update tenants set settings = jsonb_build_object('hidden', true) where id = :t", {"t": world["hotel_b"]}) == 1
    res = await send(world, dev("huntress", "H", "h1", "TEST-PC", "SERIAL-T1"), dev("huntress", "H", "h2", "REAL-PC", "SERIAL-T2"))
    assert res.followed == 1
    assert (await held(world, "group"))[0] == [("TEST-PC", ["huntress"])]
    _a, a_items = await held(world, "hotel_a")
    moved = next(s for s in a_items[0].sources if s.vendor == "huntress")
    assert moved.details.get("followed_from_client") == str(world["group"])
