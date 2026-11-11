"""Automatic installs on a REAL Postgres: where a tool is missing on a Windows or Mac machine NinjaOne manages, the install script for its OS is requested once, only for clients that already use the tool.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.models.tool_deploy_rule import ToolDeployRule
from app.services import tool_deploy_rules as svc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]

NOW = datetime.now(UTC)
AGENT = "aaaaaaaa-1111-2222-3333-444444444444"
SCRIPTS = {
    201: SimpleNamespace(id=201, name="Install Huntress (Windows)", one_click=False),
    202: SimpleNamespace(id=202, name="Install Huntress (Mac)", one_click=False),
}


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, uses, lacks, excluded = (uuid.uuid4() for _ in range(4))
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'owner', :s)"), {"t": owner, "s": f"own-{owner.hex[:10]}"})
        for t, name, settings in ((uses, "uses", {}), (lacks, "lacks", {}), (excluded, "excluded", {"tool_exclusions": ["huntress"]})):
            await s.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, settings) values (:t, :n, :s, :p, cast(:set as jsonb))"),
                {"t": t, "n": name, "s": f"{name}-{t.hex[:10]}", "p": owner, "set": json.dumps(settings)},
            )

        async def device(tenant, host, os_text, vendors, last_contact=None):
            did = uuid.uuid4()
            await s.execute(
                text("insert into devices (id, tenant_id, hostname, os) values (:i, :t, :h, :o)"),
                {"i": did, "t": tenant, "h": host, "o": os_text},
            )
            for v in vendors:
                details = {"last_contact": (last_contact or NOW - timedelta(hours=1)).isoformat()} if v == "ninjaone" else {}
                if v == "addigy":
                    details = {"url": f"https://app.addigy.com/devices/{AGENT}"}
                await s.execute(
                    text(
                        "insert into device_sources (id, tenant_id, device_id, vendor, external_id, name, details) values (gen_random_uuid(), :t, :d, :v, :e, :h, cast(:det as jsonb))"
                    ),
                    {"t": tenant, "d": did, "v": v, "e": f"{v}-{host}", "h": host, "det": json.dumps(details)},
                )

        await device(uses, "HAS-HUNTRESS", "Windows 11 Pro", ["ninjaone", "huntress"])
        await device(uses, "WIN-GAP", "Windows 11 Pro", ["ninjaone"])
        await device(uses, "MAC-GAP", "macOS 14.5", ["ninjaone"])
        await device(uses, "MAC-ADDIGY", "macOS 14.5", ["addigy"])
        await device(uses, "LINUX-GAP", "Ubuntu 22.04", ["ninjaone"])
        await device(uses, "WIN-OLD", "Windows 10 Pro", ["ninjaone"], last_contact=NOW - timedelta(days=40))
        await device(lacks, "NO-HUNTRESS-ANYWHERE", "Windows 11 Pro", ["ninjaone"])
        await device(excluded, "EXCL-A", "Windows 11 Pro", ["ninjaone", "huntress"])
        await device(excluded, "EXCL-GAP", "Windows 11 Pro", ["ninjaone"])
        await s.commit()
        s.info.update(owner=owner, uses=uses, lacks=lacks, excluded=excluded)
        yield s
        await off(s)
        for tbl in ("vendor_actions", "device_sources", "devices"):
            await s.execute(
                text(f"delete from {tbl} where tenant_id in (:a, :b, :c, :d)"), {"a": owner, "b": uses, "c": lacks, "d": excluded}
            )
        await s.execute(text("delete from tool_deploy_rules where tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id = :o"), {"o": owner})
        await s.commit()
    await engine.dispose()


def make_rule(db, windows=201, mac=202, scope="all", tool="huntress", via_addigy=False):
    rule = ToolDeployRule(
        id=uuid.uuid4(),
        tenant_id=db.info["owner"],
        tool=tool,
        scope=scope,
        client_tenant_id=db.info["uses"] if scope == "client" else None,
        windows_script_id=windows,
        mac_script_id=mac,
        via_addigy=via_addigy,
        created_at=NOW,
    )
    db.add(rule)
    return rule


async def requests(db):
    await off(db)
    rows = (
        await db.execute(
            text("select params from vendor_actions where action = 'run_script' and tenant_id in (:a, :b, :c, :d)"),
            {"a": db.info["owner"], "b": db.info["uses"], "c": db.info["lacks"], "d": db.info["excluded"]},
        )
    ).all()
    return {r[0]["device"]: r[0] for r in rows}


async def test_only_windows_and_mac_machines_in_the_gap_of_a_client_that_uses_the_tool_get_the_install_for_their_os(world):
    await off(world)
    rule = make_rule(world)
    await world.flush()
    n = await svc.queue_for_rule(world, rule, SCRIPTS, NOW)
    await world.commit()
    got = await requests(world)
    assert (
        set(got) == {"WIN-GAP", "MAC-GAP"}
    ), "not: one that has it, a Mac only in Addigy, a Linux box, one offline for weeks, a client with no Huntress anywhere, a client marked as not using it"
    assert n == 2
    assert got["WIN-GAP"]["script_id"] == 201 and got["MAC-GAP"]["script_id"] == 202
    assert got["WIN-GAP"]["deploy_rule_id"] == str(rule.id) and "WIN-GAP" in got["WIN-GAP"]["create_ticket"]["summary"]


async def test_a_machine_is_asked_for_once_not_on_every_pass_even_after_a_failure(world):
    await off(world)
    rule = make_rule(world)
    await world.flush()
    await svc.queue_for_rule(world, rule, SCRIPTS, NOW)
    await world.commit()
    await off(world)
    await world.execute(text("update vendor_actions set status = 'failed' where action = 'run_script'"))
    await world.commit()
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW + timedelta(hours=3)) == 0
    await world.commit()
    assert len(await requests(world)) == 2
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW + timedelta(days=15)) == 2, "after two weeks it asks again"


async def test_a_machine_kind_with_no_script_is_left_alone_and_a_client_rule_covers_only_its_client(world):
    await off(world)
    rule = make_rule(world, mac=None, scope="client")
    await world.flush()
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW) == 1
    await world.commit()
    assert set(await requests(world)) == {"WIN-GAP"}
    await off(world)
    gone = make_rule(world, windows=999, tool="screenconnect")
    await world.flush()
    assert await svc.queue_for_rule(world, gone, SCRIPTS, NOW) == 0, "a script CORE has not switched on is never asked for"


async def test_the_per_pass_cap_limits_how_many_machines_one_rule_asks_for(world, monkeypatch):
    monkeypatch.setattr(svc, "MAX_PER_RULE_PASS", 1)
    await off(world)
    rule = make_rule(world)
    await world.flush()
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW) == 1
    await world.commit()
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW + timedelta(minutes=5)) == 1, "the next pass takes the next one"


async def addigy_requests(db):
    await off(db)
    rows = (
        await db.execute(
            text("select params, tenant_id from vendor_actions where action = 'addigy_push' and tenant_id in (:a, :b, :c, :d)"),
            {"a": db.info["owner"], "b": db.info["uses"], "c": db.info["lacks"], "d": db.info["excluded"]},
        )
    ).all()
    return {r[0]["device"]: r[0] for r in rows}


async def test_an_addigy_only_mac_gets_a_push_request_with_its_agent_id_only_when_the_rule_says_so_and_only_once(world):
    await off(world)
    plain = make_rule(world)
    await world.flush()
    await svc.queue_for_rule(world, plain, SCRIPTS, NOW)
    await world.commit()
    assert await addigy_requests(world) == {}, "a rule without via_addigy never asks Addigy"
    await off(world)
    rule = make_rule(world, windows=None, mac=None, via_addigy=True, tool="huntress")
    rule.scope, rule.client_tenant_id = "client", world.info["uses"]
    await world.flush()
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW) == 1
    await world.commit()
    got = await addigy_requests(world)
    assert set(got) == {"MAC-ADDIGY"}, "not the Windows or Ninja machines, not the Mac Ninja manages, not another client"
    assert (
        got["MAC-ADDIGY"]["agent_id"] == AGENT
        and got["MAC-ADDIGY"]["tool"] == "huntress"
        and got["MAC-ADDIGY"]["deploy_rule_id"] == str(rule.id)
    )
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW + timedelta(hours=3)) == 0, "asked once, not every pass"
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW + timedelta(days=15)) == 1, "after two weeks it asks again"
