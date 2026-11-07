"""Script rules on a REAL Postgres: a rule runs the Windows or the Mac script by the machine's operating system, only for machines NinjaOne manages, decides each alert once, and never twice.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.models.alert_script_rule import AlertScriptRule
from app.services import alert_script_rules as svc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
TITLE = "ScreenConnect for another server (514f) found on SOMEHOST"
SCRIPTS = {
    101: SimpleNamespace(id=101, name="Remove rogue ScreenConnect (Windows)", one_click=False),
    102: SimpleNamespace(id=102, name="Remove rogue ScreenConnect (Mac)", one_click=True),
}


def rule_stub(**over):
    base = {"requires_tool": None, "windows_script_id": 101, "mac_script_id": 102}
    return SimpleNamespace(**{**base, **over})


def test_the_operating_system_is_read_from_the_text_a_tool_gave():
    assert svc.os_family("Windows 11 Pro") == "windows" and svc.os_family("Microsoft Windows Server 2022") == "windows"
    assert svc.os_family("macOS 14.5") == "mac" and svc.os_family("Mac OS X 10.15") == "mac" and svc.os_family("Darwin 23") == "mac"
    assert (
        svc.os_family("Ubuntu 22.04") is None
        and svc.os_family("iOS 17") is None
        and svc.os_family(None) is None
        and svc.os_family("") is None
    )


def test_the_decision_picks_the_script_by_os_and_says_why_it_will_not_run():
    ninja = {"ninjaone", "screenconnect"}
    ok = svc.decide(rule=rule_stub(), device="D1", facts=("windows", ninja), tool_in_use=True, scripts=SCRIPTS)
    assert ok == ("run", (SCRIPTS[101], "D1"))
    assert svc.decide(rule=rule_stub(), device="D1", facts=("mac", ninja), tool_in_use=True, scripts=SCRIPTS)[1][0].id == 102

    def skip(**kw):
        args = {"rule": rule_stub(), "device": "D1", "facts": ("windows", ninja), "tool_in_use": True, "scripts": SCRIPTS, **kw}
        return svc.decide(**args)

    assert skip(device=None)[0] == "skip"
    assert "no machine named D1" in skip(facts=None)[1]
    assert "not a Windows or Mac" in skip(facts=(None, ninja))[1]
    assert "not managed in NinjaOne" in skip(facts=("mac", {"addigy"}))[1] and "addigy" in skip(facts=("mac", {"addigy"}))[1]
    assert "no machine with huntress" in skip(rule=rule_stub(requires_tool="huntress"), tool_in_use=False)[1]
    assert skip(rule=rule_stub(requires_tool="huntress"), tool_in_use=True)[0] == "run"
    assert "no Mac script" in skip(rule=rule_stub(mac_script_id=None), facts=("mac", ninja))[1]
    assert "not switched" in skip(scripts={})[1]


pytestmark_pg = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, client, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'owner', :s)"), {"t": owner, "s": f"own-{owner.hex[:10]}"})
        for t, name in ((client, "client"), (other, "other")):
            await s.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": t, "n": name, "s": f"{name}-{t.hex[:10]}", "p": owner},
            )
        ids: dict[str, uuid.UUID] = {}

        async def device(host, os, vendors, tenant=client):
            did = uuid.uuid4()
            await s.execute(
                text("insert into devices (id, tenant_id, hostname, os) values (:i, :t, :h, :o)"),
                {"i": did, "t": tenant, "h": host, "o": os},
            )
            for v in vendors:
                await s.execute(
                    text(
                        "insert into device_sources (id, tenant_id, device_id, vendor, external_id, name) values (gen_random_uuid(), :t, :d, :v, :e, :h)"
                    ),
                    {"t": tenant, "d": did, "v": v, "e": f"{v}-{host}", "h": host},
                )

        await device("WIN1", "Windows 11 Pro", ["ninjaone", "screenconnect"])
        await device("MAC1", "macOS 14.5", ["ninjaone", "screenconnect"])
        await device("MAC2", "macOS 14.5", ["addigy"])
        await device("LIN1", "Ubuntu 22.04", ["ninjaone"])
        await device("OTHERWIN", "Windows 11 Pro", ["ninjaone", "screenconnect"], tenant=other)

        async def alert(key, host, minutes_ago=5, title=TITLE, status="new", tenant=client, enrichment=None):
            ids[key] = uuid.uuid4()
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, raw_event, enrichment_data, created_at, updated_at) "
                    "values (:i, :t, :title, 'low', :st, 50, cast(:hosts as jsonb), cast(:raw as jsonb), cast(:enr as jsonb), :at, :at)"
                ),
                {
                    "i": ids[key],
                    "t": tenant,
                    "title": title,
                    "st": status,
                    "hosts": json.dumps([host] if host else []),
                    "raw": json.dumps({"source": "aisoc-remote-tools"}),
                    "enr": json.dumps(enrichment or {}),
                    "at": NOW - timedelta(minutes=minutes_ago),
                },
            )

        await alert("win", "WIN1")
        await alert("mac", "MAC1")
        await alert("addigy_mac", "MAC2")
        await alert("linux", "LIN1")
        await alert("unknown_machine", "NOPE")
        await alert("no_host", None)
        await alert("ticketed", "WIN1", enrichment={"tickets": [{"system": "halopsa", "id": "555"}]})
        await alert("old", "WIN1", minutes_ago=600)
        await alert("resolved", "WIN1", status="resolved")
        await alert("other_title", "WIN1", title="Something else")
        await alert("other_client", "OTHERWIN", tenant=other)
        await s.commit()
        s.info.update(owner=owner, client=client, other=other, ids=ids)
        yield s
        await off(s)
        for tbl in ("vendor_actions", "alerts", "device_sources", "devices"):
            await s.execute(text(f"delete from {tbl} where tenant_id in (:a, :b, :c)"), {"a": owner, "b": client, "c": other})
        await s.execute(text("delete from alert_script_rules where tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id = :o"), {"o": owner})
        await s.commit()
    await engine.dispose()


def make_rule(db, scope="client", requires_tool=None, windows=101, mac=102):
    rule = AlertScriptRule(
        id=uuid.uuid4(),
        tenant_id=db.info["owner"],
        scope=scope,
        client_tenant_id=db.info["client"] if scope == "client" else None,
        source="aisoc-remote-tools",
        signature=f"title:{TITLE}",
        title="ScreenConnect for another server",
        windows_script_id=windows,
        mac_script_id=mac,
        requires_tool=requires_tool,
        created_at=NOW - timedelta(hours=1),
    )
    db.add(rule)
    return rule


async def rows(db):
    await off(db)
    found = (
        await db.execute(
            text(
                "select alert_id, status, params, result_message from vendor_actions where tenant_id in (:a, :b, :c) and action = 'run_script'"
            ),
            {"a": db.info["owner"], "b": db.info["client"], "c": db.info["other"]},
        )
    ).all()
    by = {r[0]: r for r in found}
    return {k: by[v] for k, v in db.info["ids"].items() if v in by}


@pytest.mark.asyncio
@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL")
async def test_each_covered_alert_runs_the_script_for_its_os_or_records_why_not_and_only_covered_alerts_are_touched(world):
    await off(world)
    rule = make_rule(world)
    await world.flush()
    n = await svc.queue_for_rule(world, rule, SCRIPTS, NOW)
    await world.commit()
    got = await rows(world)
    assert set(got) == {
        "win",
        "mac",
        "addigy_mac",
        "linux",
        "unknown_machine",
        "no_host",
        "ticketed",
    }, "new alerts of the type in this client; not older, finished, other title, or another client"
    assert n == 3
    assert (got["win"][1], got["win"][2]["script_id"], got["win"][2]["device"]) == ("pending", 101, "WIN1")
    assert (got["mac"][1], got["mac"][2]["script_id"]) == ("pending", 102)
    assert (
        got["ticketed"][2]["ticket_id"] == "555" and "create_ticket" not in got["ticketed"][2]
    ), "the result goes on the ticket the alert already has"
    assert "create_ticket" in got["win"][2] and got["win"][2]["rule_id"] == str(rule.id)
    for key, why in (
        ("addigy_mac", "not managed in NinjaOne"),
        ("linux", "not a Windows or Mac"),
        ("unknown_machine", "no machine named"),
        ("no_host", "does not name a machine"),
    ):
        assert got[key][1] == "failed" and why in got[key][3], key


@pytest.mark.asyncio
@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL")
async def test_a_second_pass_decides_nothing_again_even_after_a_failure(world):
    await off(world)
    rule = make_rule(world)
    await world.flush()
    await svc.queue_for_rule(world, rule, SCRIPTS, NOW)
    await world.commit()
    await off(world)
    await world.execute(text("update vendor_actions set status = 'failed' where action = 'run_script' and status = 'pending'"))
    await world.commit()
    before = await rows(world)
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW) == 0
    await world.commit()
    assert {k: r[0] for k, r in (await rows(world)).items()} == {k: r[0] for k, r in before.items()}
    await off(world)
    count = (
        await world.execute(
            text("select count(*) from vendor_actions where action = 'run_script' and tenant_id = :c"), {"c": world.info["client"]}
        )
    ).scalar_one()
    assert count == len(before), "one row per alert, ever"


@pytest.mark.asyncio
@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL")
async def test_the_source_alert_is_covered_though_older_and_a_required_tool_the_client_lacks_stops_the_rule(world):
    await off(world)
    rule = make_rule(world, requires_tool="huntress")
    await world.flush()
    assert await svc.queue_for_rule(world, rule, SCRIPTS, NOW, source_alert_id=world.info["ids"]["old"]) == 0
    await world.commit()
    got = await rows(world)
    assert "old" in got and got["old"][1] == "failed" and "no machine with huntress" in got["old"][3]
    assert got["win"][1] == "failed", "every covered alert is decided, with the reason"
    await off(world)
    rule2 = make_rule(world, requires_tool="screenconnect")
    rule2.signature = f"title:{TITLE}"
    await world.flush()
    await world.execute(text("delete from vendor_actions where action = 'run_script'"))
    await world.commit()
    assert (
        await svc.queue_for_rule(world, rule2, SCRIPTS, NOW, source_alert_id=world.info["ids"]["old"]) == 4
    ), "win, mac, ticketed and the older source alert, all on NinjaOne machines with ScreenConnect in use"


@pytest.mark.asyncio
@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL")
async def test_it_waits_while_a_ticket_request_or_another_script_is_in_flight_for_the_alert(world):
    await off(world)
    ids = world.info["ids"]
    client = world.info["client"]
    await world.execute(
        text(
            "insert into vendor_actions (id, tenant_id, alert_id, vendor, incident_uid, action, params, status, created_at) values (gen_random_uuid(), :t, :a, 'core', 'x', 'create_ticket', '{}'::jsonb, 'pending', now())"
        ),
        {"t": client, "a": ids["win"]},
    )
    await world.execute(
        text(
            "insert into vendor_actions (id, tenant_id, alert_id, vendor, incident_uid, action, params, status, created_at) values (gen_random_uuid(), :t, :a, 'core', 'x', 'run_script', '{\"rule_id\": \"other\"}'::jsonb, 'claimed', now())"
        ),
        {"t": client, "a": ids["mac"]},
    )
    rule = make_rule(world)
    await world.flush()
    await svc.queue_for_rule(world, rule, SCRIPTS, NOW)
    await world.commit()
    mine = {k: r for k, r in (await rows(world)).items() if r[2].get("rule_id") == str(rule.id)}
    assert "win" not in mine, "its ticket is still being opened: wait, so the result goes on that one ticket"
    assert "mac" not in mine, "another script is already running for it"
    assert "linux" in mine
