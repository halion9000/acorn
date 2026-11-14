"""Run a script on several picked devices, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

One request per machine is queued for CORE (which holds the NinjaOne and HaloPSA keys), each opening its own ticket, all in one batch so CORE asks once. Nothing runs here.
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import devices_scripts as ep
from app.db.rls import set_rls_context
from fastapi import HTTPException
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
SCRIPTS = [{"id": 7, "name": "Disk Space Scan", "one_click": False}]


@pytest.fixture
async def world():
    owner, acme, birch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    d1, d2, d3, d4 = (uuid.uuid4() for _ in range(4))
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent, settings in (
            (owner, "Live Oak", None, {"core_scripts": SCRIPTS}),
            (acme, "Acme Dental", owner, {}),
            (birch, "Birch Law", owner, {}),
        ):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, settings) values (:t, :n, :s, :p, cast(:x as jsonb))"),
                {"t": tid, "n": name, "s": f"ds-{tag}-{str(tid)[:6]}", "p": parent, "x": json.dumps(settings)},
            )
        await conn.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:p, 'halopsa', '4242', 'Acme Dental', 'acme dental', :c, false, 'manual')"
            ),
            {"p": owner, "c": acme},
        )
        for did, tid, host in (
            (d1, acme, "FRONT-DESK-PC"),
            (d2, acme, "front-desk-pc"),
            (d3, birch, "BIRCH-SRV1"),
            (d4, acme, "ACME-LAP2"),
        ):
            await conn.execute(
                text("insert into devices (id, tenant_id, hostname, alt_serials) values (:i, :t, :h, '{}')"),
                {"i": did, "t": tid, "h": host},
            )
    w = SimpleNamespace(
        owner=owner,
        acme=acme,
        birch=birch,
        d=(d1, d2, d3, d4),
        user=SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com"),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [owner, acme, birch]})
    await engine.dispose()


async def as_app(w, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await work(db)
    finally:
        await engine.dispose()


async def owner_rows(sql, params=None):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("set session_replication_role = replica"))
            return (await conn.execute(text(sql), params or {})).all()
    finally:
        await engine.dispose()


def req(w, ids, preview=False, script_id=7):
    request = SimpleNamespace(client=None, headers={})
    body = ep.BulkDeviceRun(script_id=script_id, device_ids=list(ids), preview=preview)
    return as_app(w, lambda db: ep.run_script_on_devices(body, request, w.user, db))


async def queued(w):
    return await owner_rows(
        "select tenant_id, alert_id, incident_uid, params, status from vendor_actions where tenant_id = any(:t) and action = 'run_script'",
        {"t": [w.acme, w.birch, w.owner]},
    )


async def test_the_options_are_the_scripts_core_switched_on(world):
    out = await as_app(world, lambda db: ep.device_script_options(world.user, db))
    assert [(s.id, s.name) for s in out.scripts] == [(7, "Disk Space Scan")] and out.blocked is None


async def test_one_request_per_machine_in_one_batch_each_with_its_own_ticket_under_its_clients_halopsa_client(world):
    w = world
    out = await req(w, [w.d[0], w.d[2], w.d[3]])
    assert (out.queued, out.skipped, out.batch_id is not None) == (3, 0, True)
    rows = await queued(w)
    assert len(rows) == 3
    assert {r.params["batch_id"] for r in rows} == {out.batch_id}
    by_host = {r.params["device"]: r for r in rows}
    assert set(by_host) == {"FRONT-DESK-PC", "BIRCH-SRV1", "ACME-LAP2"}
    assert by_host["FRONT-DESK-PC"].tenant_id == w.acme and by_host["BIRCH-SRV1"].tenant_id == w.birch
    assert by_host["FRONT-DESK-PC"].params["create_ticket"]["halo_client_id"] == "4242"
    assert "halo_client_id" not in by_host["BIRCH-SRV1"].params["create_ticket"]  # Birch has no HaloPSA client mapped
    assert all(r.alert_id is None and r.status == "pending" and ":" not in r.incident_uid for r in rows)
    assert all(r.params["script_id"] == 7 and r.params["script_name"] == "Disk Space Scan" for r in rows)


async def test_a_preview_says_what_would_happen_and_queues_nothing(world):
    out = await req(world, [world.d[0], world.d[2]], preview=True)
    assert (out.preview, out.queued, out.batch_id) == (True, 2, None)
    assert await queued(world) == []


async def test_a_machine_named_twice_is_asked_for_once_and_a_second_press_does_not_stack(world):
    w = world
    out = await req(w, [w.d[0], w.d[1]])  # FRONT-DESK-PC and front-desk-pc: one machine
    assert (out.queued, out.skipped) == (1, 1)
    assert "already covers" in next(i.reason for i in out.items if i.outcome == "skipped")
    again = await req(w, [w.d[0]])
    assert (again.queued, again.skipped) == (0, 1)
    assert "already waiting" in again.items[0].reason
    assert len(await queued(w)) == 1


async def test_an_unknown_device_is_left_out_with_the_reason_and_a_script_core_has_not_switched_on_is_refused(world):
    w = world
    out = await req(w, [uuid.uuid4(), w.d[2]])
    assert (out.queued, out.skipped) == (1, 1)
    assert next(i.reason for i in out.items if i.outcome == "skipped") == "Device not found."
    with pytest.raises(HTTPException) as err:
        await req(w, [w.d[2]], script_id=99)
    assert err.value.status_code == 422
