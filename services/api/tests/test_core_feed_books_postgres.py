"""QuickBooks' monthly costs as CORE posts them, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

The costs become ``quickbooks`` entries of the Net income page: a month sent again replaces that month's entries, a zero is no entry, months not sent stay, another organization never sees them, and a typed
company-wide entry for the same month and category is not counted on top.
"""

import os
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import inbox_core_feed as feed
from app.db.rls_sessions import adopt_tenant
from app.models.finance_profit import FinanceCostEntry
from sqlalchemy import select, text
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


def body(*months, unmapped=()):
    return feed.BooksIn(months=list(months), unmapped=list(unmapped))


def month(m, **amounts):
    return feed.BooksMonthIn(month=m, **amounts)


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
            await conn.execute(text("delete from finance_cost_entries where tenant_id in (:a, :b)"), {"a": mine, "b": other})
            await conn.execute(text("delete from tenants where id in (:a, :b)"), {"a": mine, "b": other})
        await owner.dispose()
        await app.dispose()


async def send(app, token, b):
    async with AsyncSession(app) as db:
        return await feed.report_core_feed_books(token, b, db)


async def entries(app, tenant):
    async with AsyncSession(app) as db:
        await adopt_tenant(db, tenant)
        rows = (await db.execute(select(FinanceCostEntry).where(FinanceCostEntry.tenant_id == tenant))).scalars().all()
        return {(r.month, r.category, r.source): r.amount for r in rows}


async def test_each_non_zero_category_of_a_month_becomes_a_company_wide_quickbooks_entry(world):
    app, w = world
    out = await send(app, "tok-mine", body(month("2026-09", payroll_cogs=253613.67, support_software=34198.84, overhead=-100.01, travel=0)))
    assert (out.months, out.entries) == (1, 3)
    got = await entries(app, w.mine)
    assert got == {
        ("2026-09", "payroll_cogs", "quickbooks"): Decimal("253613.67"),
        ("2026-09", "support_software", "quickbooks"): Decimal("34198.84"),
        ("2026-09", "overhead", "quickbooks"): Decimal("-100.01"),
    }, "zero travel is no entry, and a negative overhead is kept"


async def test_a_month_sent_again_replaces_that_months_entries_and_leaves_other_months_and_typed_entries_alone(world):
    app, w = world
    await send(app, "tok-mine", body(month("2026-09", payroll_cogs=100, hardware=5), month("2026-08", payroll_cogs=90)))
    async with AsyncSession(app) as db:
        await adopt_tenant(db, w.mine)
        db.add(FinanceCostEntry(tenant_id=w.mine, month="2026-09", category="overhead", client_key="", client_name="", source="manual", amount=Decimal("7")))
        await db.commit()
    await send(app, "tok-mine", body(month("2026-09", payroll_cogs=120)))
    got = await entries(app, w.mine)
    assert got[("2026-09", "payroll_cogs", "quickbooks")] == Decimal("120.00"), "corrected"
    assert ("2026-09", "hardware", "quickbooks") not in got, "a category the books no longer show is gone"
    assert got[("2026-08", "payroll_cogs", "quickbooks")] == Decimal("90.00"), "a month not sent is untouched"
    assert got[("2026-09", "overhead", "manual")] == Decimal("7"), "typed entries are never removed"


async def test_another_organization_never_sees_or_changes_them(world):
    app, w = world
    await send(app, "tok-mine", body(month("2026-09", payroll_cogs=100)))
    await send(app, "tok-other", body(month("2026-09", payroll_cogs=1)))
    assert (await entries(app, w.mine))[("2026-09", "payroll_cogs", "quickbooks")] == Decimal("100.00")
    assert (await entries(app, w.other))[("2026-09", "payroll_cogs", "quickbooks")] == Decimal("1.00")


async def test_a_bad_month_is_refused_before_anything_is_stored():
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        month("2026-13x", payroll_cogs=1)
    with pytest.raises(pydantic.ValidationError):
        month("2026-09", payroll_cogs=10**12)
