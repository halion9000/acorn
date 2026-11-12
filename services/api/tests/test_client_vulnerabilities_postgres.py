"""One line per vulnerability, stored and read against a REAL Postgres (opt in with AISOC_TEST_PG_URL; the database needs migration 170)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from app.api.v1.endpoints import client_vulnerabilities as ep
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(
    not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database (with migration 170)"
)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:8]
    ids = {k: uuid.uuid4() for k in ("msp", "acme", "beta", "other_msp", "stranger")}
    engine = create_async_engine(PG_URL)
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for key, parent in (("msp", None), ("acme", ids["msp"]), ("beta", ids["msp"]), ("other_msp", None), ("stranger", ids["other_msp"])):
            await c.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, :n, :s, :p)"),
                {"i": ids[key], "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent},
            )
        for owner, vendor_id, child in (("msp", "cust-acme", "acme"), ("msp", "cust-beta", "beta"), ("other_msp", "cust-x", "stranger")):
            await c.execute(
                text(
                    "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                    "values (:t, 'cipp', :v, :n, :m, :c, false, 'manual')"
                ),
                {"t": ids[owner], "v": vendor_id, "n": vendor_id, "m": vendor_id, "c": ids[child]},
            )
    yield ids
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
    await engine.dispose()


async def run(owner, work):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            out = await work(db)
            await db.commit()
            return out
    finally:
        await engine.dispose()


def vuln(cve, software="Chrome", version="120.0", severity="high", **over):
    return ep.VulnerabilityIn(cve=cve, software=software, version=version, severity=severity, **over)


def report(client, items, snapshot=None, last=True):
    return ep.VulnerabilitiesReport(vendor="cipp", vendor_client_id=client, snapshot_id=snapshot or uuid.uuid4(), last=last, items=items)


async def send(world, owner, client, items, now=NOW, **kw):
    return await run(world[owner], lambda db: ep.apply_vulnerabilities(db, world[owner], report(client, items, **kw), now))


async def read(world, owner="msp", **params):
    defaults = {"client_id": None, "severity": None, "exploited": None, "q": None, "limit": 200, "offset": 0}
    return await run(world[owner], lambda db: ep.list_client_vulnerabilities(NS(tenant_id=world[owner]), db, **{**defaults, **params}))


async def test_each_vulnerability_is_its_own_line_named_with_its_program_machines_and_client_worst_first(world):
    out = await send(
        world,
        "msp",
        "cust-acme",
        [
            vuln("cve-2024-0001", "Chrome", "120.0", "high", cvss=8.8, devices=3, device_names=["PC-1", "PC-2", "PC-3"]),
            vuln("CVE-2024-0002", "7-Zip", "22.0", "critical", cvss=9.8, exploited=True, devices=1, device_names=["SRV-1"]),
            vuln("CVE-2024-0003", "Chrome", "120.0", "high", exploited=True, devices=1, device_names=["PC-1"]),
        ],
    )
    assert (out.accepted, out.unmapped) == (3, 0)
    await send(world, "msp", "cust-beta", [vuln("CVE-2024-0001", "Chrome", "119.0", "high", devices=9)])
    got = await read(world)
    assert (got.total, got.exploited, got.clients) == (4, 2, 2)
    assert got.by_severity == {"critical": 1, "high": 3}
    lines = [(r.client_name.split("-")[0], r.cve, r.software, r.version, r.severity, r.exploited, r.devices) for r in got.rows]
    assert lines == [
        ("acme", "CVE-2024-0002", "7-Zip", "22.0", "critical", True, 1),
        ("acme", "CVE-2024-0003", "Chrome", "120.0", "high", True, 1),
        ("beta", "CVE-2024-0001", "Chrome", "119.0", "high", False, 9),
        ("acme", "CVE-2024-0001", "Chrome", "120.0", "high", False, 3),
    ], "critical first, then a known exploit, then the one on more machines; the CVE id is stored in capitals"
    first = got.rows[0]
    assert first.device_names == ["SRV-1"] and first.cvss == pytest.approx(9.8) and first.source == "cipp"


async def test_a_later_list_replaces_the_earlier_one_keeps_first_seen_and_drops_what_was_fixed(world):
    await send(world, "msp", "cust-acme", [vuln("CVE-1", devices=2), vuln("CVE-2")], now=NOW - timedelta(days=3))
    snap = uuid.uuid4()
    part = await send(world, "msp", "cust-acme", [vuln("CVE-1", devices=5, severity="critical")], snapshot=snap, last=False)
    assert part.removed == 0
    assert (await read(world)).total == 2, "nothing is removed until the final chunk"
    done = await send(world, "msp", "cust-acme", [vuln("CVE-3")], snapshot=snap, last=True)
    assert done.removed == 1
    rows = {r.cve: r for r in (await read(world)).rows}
    assert sorted(rows) == ["CVE-1", "CVE-3"], "CVE-2 was not in the new list: it was fixed, and is gone"
    assert rows["CVE-1"].first_seen == NOW - timedelta(days=3) and rows["CVE-1"].last_seen == NOW
    assert (rows["CVE-1"].devices, rows["CVE-1"].severity) == (5, "critical"), "the newer facts replace the older"
    assert rows["CVE-3"].first_seen == NOW


async def test_the_same_entry_twice_in_one_chunk_is_stored_once_and_an_unmapped_client_waits(world):
    out = await send(world, "msp", "cust-acme", [vuln("CVE-1", devices=1), vuln("cve-1", devices=4)])
    assert out.accepted == 1
    assert [(r.cve, r.devices) for r in (await read(world)).rows] == [("CVE-1", 4)]
    waiting = await send(world, "msp", "cust-nobody", [vuln("CVE-9")])
    assert (waiting.accepted, waiting.unmapped) == (0, 1)
    assert (await read(world)).total == 1


async def test_filters_narrow_the_lines_and_the_counts_and_pages_follow_the_same_order(world):
    await send(
        world,
        "msp",
        "cust-acme",
        [
            vuln("CVE-A", "Chrome", severity="critical", exploited=True, device_names=["LAPTOP-7"]),
            vuln("CVE-B", "Firefox", severity="high"),
            vuln("CVE-C", "Chrome", "121.0", severity="medium"),
        ],
    )
    await send(world, "msp", "cust-beta", [vuln("CVE-D", "Zoom", severity="high", exploited=True)])
    assert [r.cve for r in (await read(world, client_id=world["beta"])).rows] == ["CVE-D"]
    assert [r.cve for r in (await read(world, severity="high")).rows] == ["CVE-D", "CVE-B"]
    hit = await read(world, exploited=True)
    assert ([r.cve for r in hit.rows], hit.total, hit.exploited) == (["CVE-A", "CVE-D"], 2, 2)
    assert [r.cve for r in (await read(world, q="chrome")).rows] == ["CVE-A", "CVE-C"]
    assert [r.cve for r in (await read(world, q="laptop-7")).rows] == ["CVE-A"], "a machine name finds the vulnerabilities on it"
    assert [r.cve for r in (await read(world, q="cve-b")).rows] == ["CVE-B"]
    everything = [r.cve for r in (await read(world)).rows]
    paged = [r.cve for r in (await read(world, limit=2)).rows] + [r.cve for r in (await read(world, limit=2, offset=2)).rows]
    assert paged == everything == ["CVE-A", "CVE-D", "CVE-B", "CVE-C"]
    assert (await read(world, limit=1)).total == 4, "the counts are of everything that matches, not of the page"


async def test_another_organisation_sees_none_of_it_and_cannot_ask_for_a_client_that_is_not_its_own(world):
    await send(world, "msp", "cust-acme", [vuln("CVE-1")])
    await send(world, "other_msp", "cust-x", [vuln("CVE-X")])
    assert [r.cve for r in (await read(world, "msp")).rows] == ["CVE-1"]
    assert [r.cve for r in (await read(world, "other_msp")).rows] == ["CVE-X"]
    stolen = await read(world, "other_msp", client_id=world["acme"])
    assert (stolen.total, stolen.rows) == (0, [])


async def test_the_sentence_saying_what_a_vulnerability_is_is_kept_shown_updated_and_can_be_searched(world):
    await send(
        world,
        "msp",
        "cust-acme",
        [vuln("CVE-9", "Not named by ThreatMate", "", summary="  Windows Kernel   elevation of privilege vulnerability. "), vuln("CVE-8")],
    )
    rows = {r.cve: r for r in (await read(world)).rows}
    assert rows["CVE-9"].summary == "Windows Kernel elevation of privilege vulnerability.", "kept, with its spaces tidied"
    assert rows["CVE-8"].summary == "", "a tool that gives none leaves it empty"
    assert [r.cve for r in (await read(world, q="kernel elevation")).rows] == ["CVE-9"]
    await send(world, "msp", "cust-acme", [vuln("CVE-9", "Not named by ThreatMate", "", summary="A newer sentence.")])
    assert [(r.cve, r.summary) for r in (await read(world)).rows] == [("CVE-9", "A newer sentence.")]
    with pytest.raises(ValueError):
        vuln("CVE-7", summary="x" * (ep.SUMMARY_MAX + 1))
