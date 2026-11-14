"""The HaloPSA money snapshot, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

CORE posts the snapshot with the feed token; the latest one replaces the one before; the finance endpoint works margin and ageing out of it for the organisation that owns the token, and another
organisation never sees it.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as fin_ep
from app.api.v1.endpoints import inbox_core_feed as feed
from app.db.rls_sessions import adopt_tenant
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]


def snapshot(price=25.0, invoices=None):
    return feed.FinanceSnapshotIn(
        recurring=[
            feed.FinanceRecurringIn(
                id="7",
                client_id="12",
                client_name="Acme Dental",
                period=3,
                lines=[feed.FinanceLineIn(item="Managed Endpoint", qty=10, unit_price=price, unit_cost=9)],
            )
        ],
        invoices=invoices
        if invoices is not None
        else [
            feed.FinanceInvoiceIn(
                client_id="12", client_name="Acme Dental", number="INV-1", due="2026-08-01T00:00:00", total=500, amount_due=500
            )
        ],
    )


@pytest.fixture
async def world(monkeypatch):
    mine, other = uuid.uuid4(), uuid.uuid4()
    tag = mine.hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid, name in ((mine, f"Live Oak {tag}"), (other, f"Other {tag}")):
                await conn.execute(
                    text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :n, 'parent')"), {"i": tid, "n": name}
                )
        owner_of = {"tok-mine": mine, "tok-other": other}

        async def verify(db, token):
            if token not in owner_of:
                raise AssertionError("unknown token")
            return owner_of[token]

        monkeypatch.setattr(feed, "_verify_core_feed_token", verify)
        yield app, SimpleNamespace(mine=mine, other=other)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from finance_halo_snapshots where tenant_id in (:a, :b)"), {"a": mine, "b": other})
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await owner.dispose()
        await app.dispose()


async def send(app, token, body):
    async with AsyncSession(app) as db:
        return await feed.report_core_feed_finance(token, body, db)


async def view(app, tenant):
    async with AsyncSession(app) as db:
        await adopt_tenant(db, tenant)
        return await fin_ep.halo_finance(SimpleNamespace(tenant_id=tenant), db)


async def test_nothing_is_shown_until_core_has_sent_a_snapshot(world):
    app, w = world
    assert await view(app, w.mine) == {"received_at": None, "margin": None, "aging": None}


async def test_the_snapshot_is_kept_and_margin_and_ageing_come_from_it(world):
    app, w = world
    out = await send(app, "tok-mine", snapshot())
    assert (out.recurring, out.invoices) == (1, 1)
    got = await view(app, w.mine)
    assert got["received_at"] is not None
    assert got["margin"]["clients"][0]["margin"] == "160.00"  # 10 x (25 - 9)
    assert got["aging"]["clients"][0]["owed"] == "500.00"
    assert got["aging"]["clients"][0]["buckets"]["over_90"] == "500.00"


async def test_a_newer_snapshot_replaces_the_one_before_not_adds_to_it(world):
    app, w = world
    await send(app, "tok-mine", snapshot(price=25.0))
    await send(app, "tok-mine", snapshot(price=30.0, invoices=[]))
    got = await view(app, w.mine)
    assert got["margin"]["clients"][0]["margin"] == "210.00"  # 10 x (30 - 9)
    assert got["aging"]["clients"] == []


async def test_another_organisation_never_sees_it(world):
    app, w = world
    await send(app, "tok-mine", snapshot())
    assert (await view(app, w.other))["margin"] is None
