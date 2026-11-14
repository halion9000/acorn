"""Installing the NinjaOne agent from the Devices page, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

CORE shares what can be chosen (roles, organisations, locations); a request is only QUEUED for CORE, which makes the installer link, runs it through ScreenConnect and sets the role.
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import devices_console as con
from app.api.v1.endpoints import devices_ninja_deploy as ep
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


async def add_session(device_id, tenant_id, external_id="sess-0001"):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(
                text(
                    "insert into device_sources (tenant_id, device_id, vendor, external_id, name, details) values (:t, :d, 'screenconnect', :e, 'x', '{}'::jsonb)"
                ),
                {"t": tenant_id, "d": device_id, "e": external_id},
            )
    finally:
        await engine.dispose()


OPTIONS = {
    "roles": [
        {"id": 202, "name": "WINDOWS_LAPTOP", "node_class": "WINDOWS_WORKSTATION"},
        {"id": 206, "name": "MAC_LAPTOP", "node_class": "MAC"},
    ],
    "organizations": [{"id": 27, "name": "Acme Dental", "locations": [{"id": 27, "name": "Main"}]}],
}


async def share(w, options=OPTIONS):
    import json as _json

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("update tenants set settings = cast(:s as jsonb) where id = :t"),
            {"s": _json.dumps({"ninja_deploy": options}), "t": w.owner},
        )
        await conn.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:p, 'ninjaone', '27', 'Acme Dental', 'acme dental', :c, false, 'manual')"
            ),
            {"p": w.owner, "c": w.acme},
        )
    await engine.dispose()


def options_for(w, device_id):
    return as_app(w, lambda db: ep.deploy_options(device_id, w.user, db))


def deploy(w, device_id, **over):
    request = SimpleNamespace(client=None, headers={})
    body = ep.DeployIn(**{"package": "msi", "org_id": 27, "location_id": 27, "role_id": 202, **over})
    return as_app(w, lambda db: ep.deploy(device_id, body, request, w.user, db))


async def test_nothing_can_be_deployed_until_screenconnect_knows_the_machine_and_core_has_shared_the_choices(world):
    w = world
    o = await options_for(w, w.d[0])
    assert o.blocked and "ScreenConnect has no record" in o.blocked
    await add_session(w.d[0], w.acme)
    o = await options_for(w, w.d[0])
    assert o.blocked and "has not shared" in o.blocked
    await share(w)
    o = await options_for(w, w.d[0])
    assert o.blocked is None
    assert [r.id for r in o.roles] == [202, 206]
    assert o.suggested_org_id == 27 and o.organizations[0].locations[0].name == "Main"
    assert o.suggested_package == "msi"


async def test_a_machine_ninjaone_already_has_is_refused(world):
    w = world
    await share(w)
    await add_session(w.d[0], w.acme)
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text(
                "insert into device_sources (tenant_id, device_id, vendor, external_id, name, details) values (:t, :d, 'ninjaone', '99', 'x', '{}'::jsonb)"
            ),
            {"t": w.acme, "d": w.d[0]},
        )
    await engine.dispose()
    assert "already has this machine" in ((await options_for(w, w.d[0])).blocked or "")
    with pytest.raises(HTTPException) as e:
        await deploy(w, w.d[0])
    assert e.value.status_code == 409


async def test_a_request_is_queued_for_core_with_everything_it_needs_and_audited(world):
    w = world
    await share(w)
    await add_session(w.d[0], w.acme)
    line = await deploy(w, w.d[0])
    assert line.status == "pending" and "Acme Dental / Main" in line.command and "WINDOWS_LAPTOP" in line.command
    rows = await owner_rows(
        "select vendor, action, params, status from vendor_actions where tenant_id = :t and action = 'ninja_deploy'", {"t": w.acme}
    )
    assert len(rows) == 1 and rows[0].vendor == "core" and rows[0].status == "pending"
    p = rows[0].params
    assert (p["session_id"], p["device"], p["package"], p["org_id"], p["location_id"], p["role_id"], p["role_name"]) == (
        "sess-0001",
        "FRONT-DESK-PC",
        "msi",
        27,
        27,
        202,
        "WINDOWS_LAPTOP",
    )
    audit = await owner_rows("select changes from audit_log where tenant_id = :t and action = 'devices:ninja_deploy'", {"t": w.acme})
    assert len(audit) == 1 and audit[0].changes["role"] == "WINDOWS_LAPTOP"


async def test_a_choice_nobody_offered_or_a_role_of_the_wrong_kind_is_refused(world):
    w = world
    await share(w)
    await add_session(w.d[0], w.acme)
    for over in ({"org_id": 28}, {"location_id": 99}, {"role_id": 999}, {"role_id": 206}, {"package": "pkg"}):
        with pytest.raises(HTTPException) as e:
            await deploy(w, w.d[0], **over)
        assert e.value.status_code == 422, over
    assert await owner_rows("select 1 from vendor_actions where tenant_id = :t and action = 'ninja_deploy'", {"t": w.acme}) == []


async def test_only_one_thing_waits_per_machine_and_the_deploy_shows_in_the_prompt_history(world):
    w = world
    await share(w)
    await add_session(w.d[0], w.acme)
    first = await deploy(w, w.d[0])
    with pytest.raises(HTTPException) as e:
        await deploy(w, w.d[0])
    assert e.value.status_code == 409
    request = SimpleNamespace(client=None, headers={})
    with pytest.raises(HTTPException) as e2:
        await as_app(w, lambda db: con.console_send(w.d[0], con.ConsoleIn(command="hostname"), request, w.user, db))
    assert e2.value.status_code == 409
    h = await as_app(w, lambda db: con.console_history(w.d[0], w.user, db))
    assert [x.request_id for x in h.lines] == [first.request_id]
    got = await as_app(w, lambda db: con.console_line(first.request_id, w.user, db))
    assert got.status == "pending"
