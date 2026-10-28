"""CORE's poll for actions does its work only in the tenants that hold a pending or claimed action, against a REAL Postgres.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database; the owner role). The poll used to run three statements in every client tenant on every ask, several seconds with
200 clients; now one lookup finds the tenants that hold anything and only those are worked on. The behaviour must not change: a pending action is handed out once, an old pending one
expires, an unanswered claim fails.
"""

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.api.v1.endpoints import inbox_core_feed as feed
from app.services.vendor_actions import PENDING_TTL
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    w = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "cyan")}
    w["token"] = f"aitnb_claim_{tag}"
    w["alerts"] = {k: uuid.uuid4() for k in ("acme", "birch", "cyan")}
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key in ("parent", "acme", "birch", "cyan"):
                parent = w["parent"] if key != "parent" else None
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": w[key], "n": f"cl-{key}-{tag}", "s": f"cl-{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            await conn.execute(
                text("insert into tenant_inbox_tokens (token, tenant_id, template_id, label) values (:k, :t, 'generic-json', 'core-feed')"),
                {"k": w["token"], "t": w["parent"]},
            )
            for key, aid in w["alerts"].items():
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, raw_event, dedup_hash, created_at, event_time, first_seen, last_seen) "
                        "values (:id, :t, 'Incident', 'high', 'new', cast(:raw as jsonb), :d, now(), now(), now(), now())"
                    ),
                    {"id": aid, "t": w[key], "raw": json.dumps({"finding": {"uid": f"huntress:{aid}"}}), "d": f"d-{aid}"},
                )
        yield w, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            t = [str(w[k]) for k in ("parent", "acme", "birch", "cyan")]
            for table in ("vendor_actions", "alerts", "tenant_inbox_tokens"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(cast(:t as uuid[]))"), {"t": t})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": t})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": t})
        await engine.dispose()


async def add_action(engine, w, client, status="pending", age=timedelta(0), vendor="huntress", claimed_age=None):
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await conn.execute(
            text(
                "insert into vendor_actions (tenant_id, alert_id, vendor, incident_uid, action, status, created_at, claimed_at) "
                "values (:t, :a, :v, :u, 'approve', :s, :c, :cl)"
            ),
            {
                "t": w[client],
                "a": w["alerts"][client],
                "v": vendor,
                "u": f"{vendor}:{client}",
                "s": status,
                "c": now - age,
                "cl": (now - claimed_age) if claimed_age is not None else None,
            },
        )


async def status_of(engine, w, client):
    async with engine.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        return (await conn.execute(text("select status, result_message from vendor_actions where tenant_id = :t"), {"t": w[client]})).all()


async def poll(engine, w, vendor="huntress", everywhere=False):
    """One CORE poll, with the number of UPDATE statements on vendor_actions it ran. Normally the once-a-minute pass over every tenant is not due (set so here); ``everywhere`` makes it due."""
    if everywhere:
        feed._last_full_claim.clear()
    else:
        feed._last_full_claim[w["parent"]] = time.monotonic()
    updates: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if statement.lstrip().upper().startswith("UPDATE VENDOR_ACTIONS"):
            updates.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            await s.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
            out = await feed.claim_core_feed_actions(w["token"], feed.ClaimRequest(vendor=vendor), s)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count)
    return out, len(updates)


async def test_with_nothing_pending_no_tenant_is_worked_on(world):
    w, engine = world
    out, updates = await poll(engine, w)
    assert out.actions == [] and updates == 0, "one lookup, and no statement in any of the four tenants"


async def test_only_the_tenants_that_hold_an_action_are_worked_on_and_it_is_handed_out_once(world):
    w, engine = world
    await add_action(engine, w, "acme")
    out, updates = await poll(engine, w)
    assert [a.incident_uid for a in out.actions] == ["huntress:acme"]
    assert updates == 3, "the three statements of the claim, in the one tenant that holds an action (not in all four)"
    assert [r.status for r in await status_of(engine, w, "acme")] == ["claimed"]
    again, _ = await poll(engine, w)
    assert again.actions == [], "handed out once"


async def test_an_old_pending_action_still_expires_and_an_unanswered_claim_still_fails(world):
    w, engine = world
    await add_action(engine, w, "birch", age=PENDING_TTL + timedelta(minutes=5))
    await add_action(engine, w, "cyan", status="claimed", age=timedelta(days=2), claimed_age=timedelta(days=2))
    out, updates = await poll(engine, w)
    assert out.actions == [], "an expired action is never handed out"
    assert updates == 6, "the two tenants that hold something, three statements each"
    birch = await status_of(engine, w, "birch")
    cyan = await status_of(engine, w, "cyan")
    assert [r.status for r in birch] == ["failed"] and "Expired" in birch[0].result_message
    assert [r.status for r in cyan] == ["failed"] and "did not report" in cyan[0].result_message


async def test_another_vendors_action_is_not_handed_out_but_the_tenant_is_still_tidied(world):
    w, engine = world
    await add_action(engine, w, "acme", vendor="blumira")
    out, _ = await poll(engine, w, vendor="huntress")
    assert out.actions == []
    assert [r.status for r in await status_of(engine, w, "acme")] == ["pending"]
    blumira, _ = await poll(engine, w, vendor="blumira")
    assert [a.incident_uid for a in blumira.actions] == ["blumira:acme"]


async def test_once_a_minute_every_tenant_is_worked_on_anyway_so_a_blind_lookup_only_delays(world):
    w, engine = world
    await add_action(engine, w, "cyan")
    out, updates = await poll(engine, w, everywhere=True)
    assert [a.incident_uid for a in out.actions] == ["huntress:cyan"]
    assert updates == 12, "the three statements in each of the four tenants: the safety-net pass"
    await add_action(engine, w, "acme")
    narrow, narrow_updates = await poll(engine, w)
    assert [a.incident_uid for a in narrow.actions] == [
        "huntress:acme"
    ] and narrow_updates == 6, "the next polls are narrow again (acme and the claimed cyan one hold something)"
