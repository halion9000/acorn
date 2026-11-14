"""The green dot on the Remote tools page: whether the tools say each machine is online right now, matched by name inside the client, against a REAL Postgres as the restricted role."""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import remote_tools as ep
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


async def seed(w):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        # d[0] online (NinjaOne says not offline), d[3] offline, d[1] has a device but no tool says anything.
        for did, flags in ((w.d[0], '{"offline": false}'), (w.d[3], '{"offline": true}')):
            await conn.execute(
                text(
                    "insert into device_sources (tenant_id, device_id, vendor, external_id, name, details) values (:t, :d, 'ninjaone', :e, 'x', cast(:j as jsonb))"
                ),
                {"t": w.acme, "d": did, "e": f"n-{did}", "j": flags},
            )
        for host in ("front-desk-pc.acme.local", "ACME-LAP2", "BACK-OFFICE", "no-such-device"):
            await conn.execute(
                text(
                    "insert into device_remote_tools (tenant_id, hostname_key, tool_key, instance_id, hostname, vendor, version) "
                    "values (:t, :k, 'teamviewer', '', :h, 'ninjaone', '15.0')"
                ),
                {"t": w.acme, "k": host.split(".")[0].lower(), "h": host},
            )
    await engine.dispose()


async def test_each_machine_is_marked_online_offline_or_unknown_from_the_clients_tools(world):
    w = world
    await seed(w)
    rows = await as_app(w, lambda db: ep.tool_devices("teamviewer", w.user, db))
    by_host = {r.hostname.split(".")[0].lower(): r for r in rows}
    assert by_host["front-desk-pc"].online is True, "matched by name without the domain"
    assert by_host["acme-lap2"].online is False
    assert by_host["back-office"].online is None, "no device by that name: unknown, not offline"
    assert by_host["no-such-device"].online is None
