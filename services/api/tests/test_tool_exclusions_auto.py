"""A client with nothing from a tool has the tool ticked as "not used" by itself, and unticked by itself when something shows up; a person's own choice always wins.

The pure rules first, then the whole thing against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).
"""

import os
import uuid

import pytest
from app.api.v1.endpoints import client_posture as cp
from app.db.rls import set_rls_context
from app.services import tool_exclusions as tx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

WORKING = {"huntress", "ninjaone", "dnsfilter", "screenconnect"}


def changes(settings=None, counts=None, linked=(), total=5, working=WORKING):
    return tx.auto_changes(settings or {}, counts or {}, set(linked), total, set(working))


def test_a_tool_that_works_elsewhere_and_has_nothing_for_this_client_is_ticked_by_itself():
    out = changes(counts={"ninjaone": 5})
    assert set(out["tool_exclusions"]) == {"dnsfilter", "huntress", "screenconnect"}
    assert out[tx.AUTO_KEY] == out["tool_exclusions"]
    assert "ninjaone" not in out["tool_exclusions"], "it has devices from NinjaOne"


def test_nothing_is_ticked_for_a_tool_that_reports_nothing_for_anyone_a_client_with_no_devices_or_a_linked_tool():
    assert (
        changes(counts={"ninjaone": 5}, working={"ninjaone"}) is None
    ), "no other client has devices from the others: a broken tool, not an unused one"
    assert changes(counts={}, total=0) is None, "a client that has not synced yet is not judged"
    out = changes(counts={"ninjaone": 5}, linked={"huntress"})
    assert "huntress" not in out["tool_exclusions"], "linked to a Huntress organization, so it is used"


def test_a_persons_own_tick_is_never_touched_and_a_tool_they_unticked_is_never_ticked_again():
    mine = {"tool_exclusions": ["huntress"]}
    out = changes(mine, counts={"ninjaone": 5, "huntress": 3})
    assert (
        "huntress" in out["tool_exclusions"] and tx.AUTO_KEY in out and "huntress" not in out[tx.AUTO_KEY]
    ), "theirs stays even though devices now report"
    declined = {tx.DECLINED_KEY: ["dnsfilter"]}
    out2 = changes(declined, counts={"ninjaone": 5})
    assert "dnsfilter" not in out2["tool_exclusions"]


def test_an_automatic_tick_goes_away_by_itself_when_a_device_appears_or_the_tool_is_linked_and_nothing_else_changes():
    ticked = changes(counts={"ninjaone": 5})
    after = tx.auto_changes(ticked, {"ninjaone": 5, "huntress": 1}, set(), 6, set(WORKING))
    assert "huntress" not in after["tool_exclusions"] and "huntress" not in after[tx.AUTO_KEY]
    linked = tx.auto_changes(ticked, {"ninjaone": 5}, {"screenconnect"}, 5, set(WORKING))
    assert "screenconnect" not in linked["tool_exclusions"]
    assert tx.auto_changes(ticked, {"ninjaone": 5}, set(), 5, set(WORKING)) is None, "nothing changed: nothing to write"


def test_other_settings_are_kept_and_the_tool_list_is_removed_when_it_empties():
    ticked = changes({"business_hours": "9-5"}, counts={"ninjaone": 5})
    assert ticked["business_hours"] == "9-5"
    cleared = tx.auto_changes(ticked, {t: 1 for t in tx.EXCLUDABLE}, set(), 20, set(WORKING))
    assert "tool_exclusions" not in cleared and tx.AUTO_KEY not in cleared and cleared["business_hours"] == "9-5"


def test_unticking_an_automatic_tick_declines_it_and_ticking_one_by_hand_makes_it_theirs():
    ticked = changes(counts={"ninjaone": 5})
    unticked = tx.with_person_choice(ticked, ["screenconnect", "dnsfilter"])
    assert unticked["tool_exclusions"] == ["dnsfilter", "screenconnect"]
    assert unticked[tx.DECLINED_KEY] == ["huntress"]
    assert unticked[tx.AUTO_KEY] == ["dnsfilter", "screenconnect"]
    assert changes(unticked, counts={"ninjaone": 5}) is None, "the declined one is not ticked again"
    theirs = tx.with_person_choice({tx.DECLINED_KEY: ["huntress"]}, ["huntress"])
    assert tx.DECLINED_KEY not in theirs and tx.auto_of_settings(theirs) == frozenset()


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    owner, a, b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
            {"i": owner, "n": f"ta-owner-{tag}", "s": f"ta-owner-{tag}"},
        )
        for tid, n in ((a, "a"), (b, "b")):
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role, parent_tenant_id) values (:i, :n, :s, 'child', :p)"),
                {"i": tid, "n": f"ta-{n}-{tag}", "s": f"ta-{n}-{tag}", "p": owner},
            )

        async def device(tid, vendors):
            did = uuid.uuid4()
            await conn.execute(
                text("insert into devices (id, tenant_id, hostname) values (:i, :t, :h)"),
                {"i": did, "t": tid, "h": f"PC-{uuid.uuid4().hex[:5]}"},
            )
            for v in vendors:
                await conn.execute(
                    text("insert into device_sources (tenant_id, device_id, vendor, external_id, name) values (:t, :d, :v, :e, 'x')"),
                    {"t": tid, "d": did, "v": v, "e": uuid.uuid4().hex[:8]},
                )

        # Client a: NinjaOne only. Client b: NinjaOne and Huntress (so Huntress is working somewhere).
        await device(a, ["ninjaone"])
        await device(b, ["ninjaone", "huntress"])
    yield engine, owner, a, b, device
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (owner, a, b):
            await conn.execute(text("delete from device_sources where tenant_id = :t"), {"t": t})
            await conn.execute(text("delete from devices where tenant_id = :t"), {"t": t})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [owner, a, b]})
    await engine.dispose()


async def settings_of(engine, tid):
    async with engine.begin() as conn:
        return (await conn.execute(text("select settings from tenants where id = :t"), {"t": tid})).scalar_one()


@needs_pg
@pytest.mark.asyncio
async def test_reconcile_ticks_what_a_client_has_nothing_from_and_leaves_alone_a_client_that_has_it(world):
    engine, owner, a, b, _ = world
    app = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            assert await tx.reconcile_auto(db, owner, [a, b]) >= 1
        sa, sb = await settings_of(engine, a), await settings_of(engine, b)
        assert "huntress" in (sa.get("tool_exclusions") or []), "client a has no Huntress device and Huntress works for client b"
        assert "ninjaone" not in (sa.get("tool_exclusions") or [])
        assert "huntress" not in (sb.get("tool_exclusions") or []) and "ninjaone" not in (sb.get("tool_exclusions") or [])
        assert sa["tool_exclusions_auto"] == sa["tool_exclusions"]
    finally:
        await app.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_a_device_appearing_unticks_it_and_the_page_answers_with_which_ticks_are_automatic(world):
    engine, owner, a, b, device = world
    app = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            await tx.reconcile_auto(db, owner, [a])
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            did = uuid.uuid4()
            await conn.execute(text("insert into devices (id, tenant_id, hostname) values (:i, :t, 'NEWPC')"), {"i": did, "t": a})
            await conn.execute(
                text("insert into device_sources (tenant_id, device_id, vendor, external_id, name) values (:t, :d, 'huntress', 'h1', 'x')"),
                {"t": a, "d": did},
            )
        async with async_sessionmaker(app, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            user = type("U", (), {"tenant_id": owner})()
            out = await cp.get_tool_exclusions(a, user, db)
        assert "huntress" not in out.tools and "huntress" not in out.auto
        assert "dnsfilter" not in out.tools, "nobody has DNSFilter: it is not working anywhere, so it is not judged unused"
    finally:
        await app.dispose()
