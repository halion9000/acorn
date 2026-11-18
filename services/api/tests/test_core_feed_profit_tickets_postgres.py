"""The tickets of a month as CORE posts them, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable, fully migrated database).

One row per month: sending a month again replaces that month's list, other months and other organizations are untouched, and the client detail lists the tickets of the month it shows.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as fin_ep
from app.api.v1.endpoints import inbox_core_feed as feed
from app.db.rls_sessions import adopt_tenant
from app.models.finance_profit import FinanceProfitSnapshot, FinanceProfitTickets
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"),
]


def tk(ticket_id, hours, month="2026-10", client="Acme Dental, Inc."):
    return feed.ProfitTicketIn(client=client, month=month, ticket_id=str(ticket_id), summary=f"T{ticket_id}", hours=hours, entries=1, agent_ids=["40"])


SNAP = {
    "months": ["2026-10"],
    "invoices": [{"client_id": "5", "client_name": "Acme Dental, Inc.", "month": "2026-10", "revenue": 1000, "invoices": 1}],
    "hours": [{"client": "Acme Dental, Inc.", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 6}],
    "agents": [{"id": "40", "name": "Dan Kemp", "team": "Support"}],
}


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
                await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :n, 'parent')"), {"i": tid, "n": name})
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
            for table in ("finance_profit_tickets", "finance_profit_snapshots"):
                await conn.execute(text(f"delete from {table} where tenant_id in (:a, :b)"), {"a": mine, "b": other})
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await owner.dispose()
        await app.dispose()


async def send(app, token, month, tickets):
    async with AsyncSession(app) as db:
        return await feed.report_core_feed_profit_tickets(token, feed.ProfitTicketsIn(month=month, tickets=tickets), db)


async def rows(app, tenant):
    async with AsyncSession(app) as db:
        await adopt_tenant(db, tenant)
        got = (await db.execute(select(FinanceProfitTickets).where(FinanceProfitTickets.tenant_id == tenant))).scalars().all()
        return {r.month: [t["ticket_id"] for t in r.payload] for r in got}


async def test_a_month_is_stored_replaced_when_sent_again_and_kept_apart_from_other_months_and_organizations(world):
    app, w = world
    assert (await send(app, "tok-mine", "2026-10", [tk(1, 2), tk(2, 3)])).tickets == 2
    await send(app, "tok-mine", "2026-09", [tk(7, 1, "2026-09")])
    await send(app, "tok-other", "2026-10", [tk(99, 9)])
    assert await rows(app, w.mine) == {"2026-10": ["1", "2"], "2026-09": ["7"]}
    await send(app, "tok-mine", "2026-10", [tk(3, 5)])
    assert await rows(app, w.mine) == {"2026-10": ["3"], "2026-09": ["7"]}, "the month was replaced, the other month stayed"
    assert await rows(app, w.other) == {"2026-10": ["99"]}, "another organization's list was never touched"
    await send(app, "tok-mine", "2026-10", [])
    assert (await rows(app, w.mine))["2026-10"] == [], "a month with no tickets is an empty list, not an old one"


async def test_the_client_detail_lists_every_ticket_of_the_month_it_shows(world):
    app, w = world
    async with AsyncSession(app) as db:
        await adopt_tenant(db, w.mine)
        db.add(FinanceProfitSnapshot(tenant_id=w.mine, payload=SNAP))
        await db.commit()
    await send(app, "tok-mine", "2026-10", [tk(i, 0.1) for i in range(1, 121)] + [tk(500, 3.5)] + [tk(600, 9, client="Birch Law")])
    async with AsyncSession(app) as db:
        await adopt_tenant(db, w.mine)
        out = await fin_ep.profitability_client(SimpleNamespace(tenant_id=w.mine, user_id=None), db, "5", "2026-10")
    listed = out["tickets"]["rows"]
    assert len(listed) == 121 and listed[0]["ticket_id"] == "500", "all of this client's tickets, most hours first, none of another client's"
    assert out["tickets"]["other_hours"] == 0.0, "the hours listed are at least all the hours worked: nothing is left over"
