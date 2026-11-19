"""Saved remote scripts: managed with connectors:write, run with scripts:run, each machine answering on its own, against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import devices_saved_scripts as ep
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
def _refuse(permission):
    raise HTTPException(status_code=403, detail="no")


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
        user=SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com", has_permission=lambda p: True, require_permission=lambda p: None),
        runner=SimpleNamespace(tenant_id=owner, user_id=None, email="tech@goliveoak.com", has_permission=lambda p: False, require_permission=lambda p: None),
        nobody=SimpleNamespace(tenant_id=owner, user_id=None, email="x@goliveoak.com", has_permission=lambda p: False, require_permission=_refuse),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from remote_scripts where tenant_id = :o"), {"o": owner})
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



REQUEST = SimpleNamespace(client=None, headers={})


async def add(w, name="Reboot", command="shutdown /r /t 60", enabled=True):
    return await as_app(w, lambda db: ep.create_script(ep.ScriptIn(name=name, command=command, enabled=enabled), w.user, db))


async def test_a_script_is_saved_listed_changed_and_switched_off_and_a_name_cannot_repeat(world):
    w = world
    s = await add(w)
    with pytest.raises(HTTPException) as dup:
        await add(w, name="reboot")
    assert dup.value.status_code == 409
    await add(w, name="Flush DNS", command="ipconfig /flushdns", enabled=False)
    mine = await as_app(w, lambda db: ep.list_scripts(w.user, db))
    assert [(x.name, x.enabled) for x in mine] == [("Flush DNS", False), ("Reboot", True)], "a manager sees every script"
    runner_sees = await as_app(w, lambda db: ep.list_scripts(w.runner, db))
    assert [x.name for x in runner_sees] == ["Reboot"], "a person who may only run scripts sees the ones switched on"
    with pytest.raises(HTTPException) as no:
        await as_app(w, lambda db: ep.list_scripts(w.nobody, db))
    assert no.value.status_code == 403
    changed = await as_app(w, lambda db: ep.patch_script(s.id, ep.ScriptPatch(command="shutdown /r /t 120", enabled=False), w.user, db))
    assert changed.command == "shutdown /r /t 120" and changed.enabled is False
    await as_app(w, lambda db: ep.delete_script(s.id, w.user, db))
    assert [x.name for x in await as_app(w, lambda db: ep.list_scripts(w.user, db))] == ["Flush DNS"]


async def test_running_needs_confirmation_and_a_script_that_is_on_and_queues_the_saved_command_for_each_machine(world):
    w = world
    await add_session(w.d[0], w.acme, "sess-1")
    s = await add(w)
    with pytest.raises(HTTPException) as unconfirmed:
        await as_app(w, lambda db: ep.run_script(s.id, ep.RunIn(device_ids=[w.d[0]]), REQUEST, w.runner, db))
    assert unconfirmed.value.status_code == 422
    results = await as_app(w, lambda db: ep.run_script(s.id, ep.RunIn(device_ids=[w.d[0], w.d[0]], confirm=True), REQUEST, w.runner, db))
    assert len(results) == 1, "a machine named twice is sent once"
    assert results[0].line is not None and results[0].line.command == "shutdown /r /t 60"
    rows = await owner_rows("select params from vendor_actions where tenant_id = :t and action = 'sc_command'", {"t": w.acme})
    assert rows[0].params["command"] == "shutdown /r /t 60"
    audit = await owner_rows("select changes from audit_log where tenant_id = :t and action = 'devices:script_run'", {"t": w.acme})
    assert len(audit) == 1
    off = await add(w, name="Off one", command="hostname", enabled=False)
    with pytest.raises(HTTPException) as switched_off:
        await as_app(w, lambda db: ep.run_script(off.id, ep.RunIn(device_ids=[w.d[0]], confirm=True), REQUEST, w.runner, db))
    assert switched_off.value.status_code == 409


async def test_each_machine_answers_on_its_own_a_refusal_does_not_stop_the_others(world):
    w = world
    await add_session(w.d[0], w.acme, "sess-1")
    await add_session(w.d[3], w.acme, "sess-4")
    s = await add(w, command="gpupdate /force")
    # d[1] has no ScreenConnect record
    results = await as_app(w, lambda db: ep.run_script(s.id, ep.RunIn(device_ids=[w.d[0], w.d[1], w.d[3]], confirm=True), REQUEST, w.runner, db))
    assert [(r.line is not None, r.refused is not None) for r in results] == [(True, False), (False, True), (True, False)]
    assert "ScreenConnect has no record" in (results[1].refused or "")
    again = await as_app(w, lambda db: ep.run_script(s.id, ep.RunIn(device_ids=[w.d[0]], confirm=True), REQUEST, w.runner, db))
    assert again[0].refused and "still waiting" in again[0].refused, "a machine still busy with the first run is refused"


def test_a_run_names_at_most_25_machines_and_at_least_one():
    with pytest.raises(Exception):
        ep.RunIn(device_ids=[uuid.uuid4() for _ in range(26)])
    with pytest.raises(Exception):
        ep.RunIn(device_ids=[])
