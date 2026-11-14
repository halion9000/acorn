"""The command prompt on the Devices page, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

A command is only QUEUED for CORE (which holds the ScreenConnect secret); the machine's answer, once CORE reports it, is what the prompt reads back.
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import devices_console as ep
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


def send(w, device_id, command):
    request = SimpleNamespace(client=None, headers={})
    return as_app(w, lambda db: ep.console_send(device_id, ep.ConsoleIn(command=command), request, w.user, db))


def history(w, device_id):
    return as_app(w, lambda db: ep.console_history(device_id, w.user, db))


async def test_a_machine_with_no_screenconnect_record_cannot_be_sent_a_command(world):
    w = world
    h = await history(w, w.d[0])
    assert h.available is False and "no record" in (h.blocked or "")
    with pytest.raises(HTTPException) as e:
        await send(w, w.d[0], "hostname")
    assert e.value.status_code == 409


async def test_a_command_is_queued_for_core_with_the_session_and_audited_with_its_text(world):
    w = world
    await add_session(w.d[0], w.acme)
    line = await send(w, w.d[0], "  hostname  ")
    assert line.status == "pending" and line.command == "hostname"
    rows = await owner_rows(
        "select tenant_id, vendor, action, params, status from vendor_actions where tenant_id = :t and action = 'sc_command'", {"t": w.acme}
    )
    assert len(rows) == 1
    assert rows[0].vendor == "core" and rows[0].status == "pending"
    assert rows[0].params == {"session_id": "sess-0001", "command": "hostname", "device": "FRONT-DESK-PC"}
    audit = await owner_rows("select changes from audit_log where tenant_id = :t and action = 'devices:console_command'", {"t": w.acme})
    assert len(audit) == 1 and audit[0].changes["command"] == "hostname"


async def test_a_second_command_waits_until_the_first_has_an_answer_and_the_answer_is_read_back(world):
    w = world
    await add_session(w.d[0], w.acme)
    first = await send(w, w.d[0], "hostname")
    with pytest.raises(HTTPException) as e:
        await send(w, w.d[0], "whoami")
    assert e.value.status_code == 409
    # CORE reports the machine's answer.
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("update vendor_actions set status = 'done', result_message = :m, finished_at = now() where id = :i"),
            {"m": "FRONT-DESK-PC", "i": first.request_id},
        )
    await engine.dispose()
    got = await as_app(w, lambda db: ep.console_line(first.request_id, w.user, db))
    assert got.status == "done" and got.output == "FRONT-DESK-PC"
    second = await send(w, w.d[0], "whoami")
    assert second.status == "pending"
    h = await history(w, w.d[0])
    assert [x.command for x in h.lines] == ["hostname", "whoami"]
    assert h.available is True


async def test_another_machines_commands_are_not_in_this_ones_history_and_an_unknown_command_is_not_found(world):
    w = world
    await add_session(w.d[0], w.acme, "sess-a")
    await add_session(w.d[3], w.acme, "sess-b")
    await send(w, w.d[0], "hostname")
    await send(w, w.d[3], "ipconfig")
    assert [x.command for x in (await history(w, w.d[3])).lines] == ["ipconfig"]
    with pytest.raises(HTTPException) as e:
        await as_app(w, lambda db: ep.console_line(uuid.uuid4(), w.user, db))
    assert e.value.status_code == 404
