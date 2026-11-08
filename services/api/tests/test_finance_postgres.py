"""Prices and margins on a REAL Postgres: a price is saved and replaced (one row per invoice line), the margin uses the HaloPSA billed quantities of each client, and another owner's prices are never used.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as finance_ep
from app.api.v1.endpoints.finance import PriceIn, list_prices, margin, save_price
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    # The audit log is append-only (a scratch tenant with entries could not be cleaned up); that the entry is written is the endpoint's own, shared code.
    async def noop(**_kw):
        return None

    monkeypatch.setattr(finance_ep, "emit_audit", noop)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, other, client = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t, name in ((owner, "owner"), (other, "other")):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": t, "n": name, "s": f"{name}-{t.hex[:10]}"})
        await s.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, 'Acme Test', :s, :p)"), {"t": client, "s": f"cl-{client.hex[:10]}", "p": owner})
        for item, count, unit in (("Huntress per endpoint", 10, "device"), ("Unpriced line", 2, "device"), ("Tickets last month", 40, "ticket")):
            await s.execute(
                text("insert into client_license_counts (tenant_id, source, item, unit, count, first_seen_at, updated_at) values (:t, 'halopsa', :i, :u, :c, :n, :n)"),
                {"t": client, "i": item, "u": unit, "c": count, "n": NOW},
            )
        await s.commit()
        s.info.update(owner=owner, other=other, client=client)
        yield s
        await off(s)
        for tbl in ("client_license_counts",):
            await s.execute(text(f"delete from {tbl} where tenant_id = :c"), {"c": client})
        await s.execute(text("delete from finance_item_prices where tenant_id in (:a, :b)"), {"a": owner, "b": other})
        await s.execute(text("delete from tenants where parent_tenant_id = :o"), {"o": owner})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": owner, "b": other})
        await s.commit()
    await engine.dispose()


def user(tenant):
    return SimpleNamespace(tenant_id=tenant, user_id=None)  # no users row in this scratch database: the audit entry then has no actor


async def test_a_price_is_saved_once_per_line_and_the_margin_uses_the_billed_quantities(world):
    s = world
    owner = user(s.info["owner"])
    await off(s)
    await save_price(PriceIn(invoice_item="Huntress per endpoint", unit_price=Decimal("6"), unit_cost=Decimal("3.5")), None, owner, s)
    await off(s)
    again = await save_price(PriceIn(invoice_item="  Huntress  per endpoint ", unit_price=Decimal("7"), unit_cost=Decimal("3.5")), None, owner, s)
    assert again.unit_price == "7.00", "the same line is replaced, not duplicated"
    await off(s)
    got = await list_prices(owner, s)
    assert [p.invoice_item for p in got.prices] == ["Huntress per endpoint"]
    assert got.billed_items == ["Huntress per endpoint", "Unpriced line"], "a count of tickets is not an invoice line"
    await off(s)
    out = await margin(owner, s)
    (row,) = out["clients"]
    assert (row["client_name"], row["revenue"], row["cost"], row["margin"]) == ("Acme Test", "70.00", "35.00", "35.00")
    assert row["unpriced_items"] == ["Unpriced line"]
    assert out["priced_items"] == 1


async def test_another_owners_prices_are_never_used(world):
    s = world
    await off(s)
    await save_price(PriceIn(invoice_item="Huntress per endpoint", unit_price=Decimal("99"), unit_cost=Decimal("1")), None, user(s.info["other"]), s)
    await off(s)
    out = await margin(user(s.info["owner"]), s)
    assert out["priced_items"] == 0
    assert out["clients"][0]["revenue"] == "0.00" and sorted(out["clients"][0]["unpriced_items"]) == ["Huntress per endpoint", "Unpriced line"]
