"""Maintenance windows against a REAL Postgres as the restricted application role (row-level security on).

A window is made by the organization (its own tenant) but hides and restores alerts that belong to a CLIENT tenant, so the writes go through ``acting_as_tenant``. The SQLite tests cannot show whether the
row-level policy lets that write through, or that it stays inside the one client. This runs the service's own functions as ``aisoc_app``: the window hides the client's open alerts except critical ones, leaves
other clients, the owner's own alerts and another organization alone, gives them back exactly as they were, and the background sweep lifts a window that has ended and ignores one that has not started.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.db import rls_hook  # noqa: F401  (installs the listener that makes a tagged session work)
from app.db.rls_sessions import mark_platform, mark_tenant
from app.models.alert_suppression import AlertSuppression
from app.services import alert_suppression as sup
from app.services.alert_status import SUPPRESSED
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

# (who, title, severity, status)
ALERTS = [
    ("acme", "acme-high", "high", "new"),
    ("acme", "acme-critical", "critical", "new"),
    ("acme", "acme-working", "low", "triaging"),
    ("birch", "birch-low", "low", "new"),
    ("owner", "owner-low", "low", "new"),
    ("stranger", "stranger-low", "low", "new"),
]


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("owner", "acme", "birch", "stranger")}
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = ids["owner"] if key in ("acme", "birch") else None
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            for who, title, severity, status in ALERTS:
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, priority, created_at, updated_at) values (gen_random_uuid(), :t, :title, :sev, :st, 50, now(), now())"
                    ),
                    {"t": ids[who], "title": f"{title}-{tag}", "sev": severity, "st": status},
                )
        yield ids, tag
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            everyone = [str(x) for x in ids.values()]
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(text("delete from alert_suppressions where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(
                text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": everyone}
            )
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": everyone})
        await owner.dispose()


async def statuses(tag):
    """The status of every test alert, read as the table owner (so the check does not depend on the policy under test)."""
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            rows = (
                await conn.execute(
                    text("select title, status, status_before_suppression from alerts where title like :p"), {"p": f"%-{tag}"}
                )
            ).all()
            return {r[0].removesuffix(f"-{tag}"): (r[1], r[2]) for r in rows}
    finally:
        await engine.dispose()


async def as_owner(ids, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            mark_tenant(db, ids["owner"])
            out = await work(db)
            await db.commit()
            return out
    finally:
        await engine.dispose()


def make_window(ids, **over):
    now = datetime.now(UTC)
    base = {
        "tenant_id": ids["owner"],
        "scope": "client",
        "client_tenant_id": ids["acme"],
        "signature": sup.WINDOW_SIGNATURE,
        "title": "Maintenance window",
        "starts_at": now - timedelta(minutes=1),
        "expires_at": now + timedelta(hours=2),
    }
    base.update(over)
    return AlertSuppression(**base)


async def test_a_window_hides_the_clients_open_alerts_except_critical_and_touches_nobody_else(world):
    ids, tag = world

    async def start(db):
        rule = make_window(ids)
        db.add(rule)
        await db.flush()
        return await sup.apply_rule(db, rule, ids["owner"])

    assert await as_owner(ids, start) == 2
    got = await statuses(tag)
    assert got["acme-high"][0] == SUPPRESSED and got["acme-high"][1] == "new"
    assert got["acme-working"][0] == SUPPRESSED and got["acme-working"][1] == "triaging", "the status it had is kept so it can be put back"
    assert got["acme-critical"] == ("new", None), "a critical alert is never hidden by a window"
    for untouched in ("birch-low", "owner-low", "stranger-low"):
        assert got[untouched] == ("new", None), f"{untouched} is not this window's client"


async def test_lifting_a_window_gives_the_alerts_back_exactly_as_they_were(world):
    ids, tag = world

    async def start(db):
        rule = make_window(ids)
        db.add(rule)
        await db.flush()
        await sup.apply_rule(db, rule, ids["owner"])
        return rule.id

    rule_id = await as_owner(ids, start)

    async def lift(db):
        rule = await db.get(AlertSuppression, rule_id)
        return await sup.release_rule(db, rule, ids["owner"])

    assert await as_owner(ids, lift) == 2
    got = await statuses(tag)
    assert got["acme-high"] == ("new", None)
    assert got["acme-working"] == ("triaging", None)


async def test_the_sweep_lifts_a_window_that_has_ended_and_waits_for_one_that_has_not_started(world):
    ids, tag = world
    now = datetime.now(UTC)

    async def start(db):
        ended = make_window(ids, starts_at=now - timedelta(hours=3), expires_at=now - timedelta(hours=1))
        db.add(ended)
        await db.flush()
        # The window ran: hide what it covered, then let the sweep find it over.
        await sup.apply_rule(db, ended, ids["owner"])
        return ended.id

    ended_id = await as_owner(ids, start)
    assert (await statuses(tag))["acme-high"][0] == SUPPRESSED

    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            mark_platform(db)
            future = make_window(
                ids, client_tenant_id=ids["birch"], starts_at=now + timedelta(hours=5), expires_at=now + timedelta(hours=8)
            )
            db.add(future)
            await db.commit()
            out = await sup.sweep(db, now)
    finally:
        await engine.dispose()

    assert out["expired"] == 1 and out["restored"] == 2, out
    got = await statuses(tag)
    assert got["acme-high"] == ("new", None) and got["acme-working"] == ("triaging", None)
    assert got["birch-low"] == ("new", None), "a window that has not started hides nothing"

    check = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with check.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            reason = (await conn.execute(text("select revoked_reason from alert_suppressions where id = :i"), {"i": ended_id})).scalar_one()
    finally:
        await check.dispose()
    assert reason == "expired"
