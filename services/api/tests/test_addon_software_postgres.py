"""Add-on software per client on a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable, fully migrated database; migration 213 applied).

CORE posts what each vendor billed; a person maps a vendor to the counts that stand behind it; Net income then carries each vendor's bill to the clients by their license counts as they stood at the end of the month.
"""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import finance as fin
from app.api.v1.endpoints import inbox_core_feed as feed
from app.db.rls import set_rls_context
from app.models.finance_profit import FinanceProfitSnapshot
from app.services.addon_loader import add_on_by_month
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"),
]
D = Decimal
SNAP = {
    "months": ["2026-09", "2026-10"],
    "invoices": [
        {"client_id": "5", "client_name": "Acme Dental, Inc.", "month": "2026-10", "revenue": 1000, "invoices": 1},
        {"client_id": "6", "client_name": "Birch Law", "month": "2026-10", "revenue": 400, "invoices": 1},
    ],
    "hours": [],
    "agents": [],
}


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(fin, "emit_audit", noop)


@pytest.fixture
async def world(monkeypatch):
    owner_t, acme, birch, other = (uuid.uuid4() for _ in range(4))
    tag = owner_t.hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :n, 'parent')"), {"i": owner_t, "n": f"Live Oak {tag}"})
            for tid, name in ((acme, "Acme Dental, Inc."), (birch, "Birch Law"), (other, "Elsewhere")):
                await conn.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, :n, :s, :p)"), {"i": tid, "n": name, "s": f"{name[:4]}-{tid.hex[:8]}".lower(), "p": owner_t if tid != other else None})
            # Acme is linked to Halo client 5 by an alias; Birch is found by its name.
            await conn.execute(
                text("insert into client_aliases (id, tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored) values (gen_random_uuid(), :o, 'halopsa', '5', 'Acme Dental, Inc.', 'acmedentalinc', :c, false)"),
                {"o": owner_t, "c": acme},
            )
            for tid, count in ((acme, 10), (birch, 30)):
                await conn.execute(text("insert into client_license_counts (tenant_id, source, item, unit, count, first_seen_at, updated_at) values (:t, 'halopsa', 'Huntress EDR', 'other', :n, now(), now())"), {"t": tid, "n": count})
            # Acme had 30 at the end of September and cut to 10 on 5 October: history decides the September split.
            await conn.execute(text("insert into client_license_history (tenant_id, source, item, unit, count, previous_count, observed_at) values (:t, 'halopsa', 'Huntress EDR', 'other', 30, null, :at)"), {"t": acme, "at": datetime(2026, 8, 1, tzinfo=UTC)})
            await conn.execute(text("insert into client_license_history (tenant_id, source, item, unit, count, previous_count, observed_at) values (:t, 'halopsa', 'Huntress EDR', 'other', 10, 30, :at)"), {"t": acme, "at": datetime(2026, 10, 5, tzinfo=UTC)})
        owner_of = {"tok": owner_t}

        async def verify(db, token):
            return owner_of[token]

        monkeypatch.setattr(feed, "_verify_core_feed_token", verify)
        yield SimpleNamespace(owner=owner_t, acme=acme, birch=birch)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            ids = [owner_t, acme, birch, other]
            for table in ("finance_vendor_costs", "finance_vendor_map", "finance_profit_snapshots", "client_license_history", "client_license_counts", "client_aliases"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(:ids)"), {"ids": ids})
            await conn.execute(text("delete from tenants where id = any(:ids)"), {"ids": ids})
        await owner.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


def cost_month(month, *rows):
    return feed.VendorCostMonthIn(month=month, rows=[feed.VendorCostRowIn(account=a, vendor=v, amount=amt) for a, v, amt in rows])


async def test_vendor_bills_replace_by_month_and_the_split_follows_the_counts_at_each_month_end(world):
    w = world
    user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="hal@x")
    req = SimpleNamespace(client=None, headers={})
    sent = await with_db(w.owner, lambda db: feed.report_core_feed_vendor_costs("tok", feed.VendorCostsIn(months=[cost_month("2026-09", ("5500", "Huntress", 100.0), ("5500", "Huntress", 20.0), ("5500", "Lonely Vendor", 50), ("5100", "Ninja", 10)), cost_month("2026-10", ("5500", "Huntress", 80.0))]), db))
    assert (sent.months, sent.rows) == (2, 4), "two Huntress lines of one month are one bill"
    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=w.owner, payload=SNAP))
        await db.commit()

    await with_db(w.owner, ingest)
    assert await with_db(w.owner, lambda db: add_on_by_month(db, w.owner, SNAP, ["2026-09", "2026-10"])) == {}, "nothing is mapped yet: nothing to carry to clients"
    await with_db(w.owner, lambda db: fin.save_vendor_map(fin.VendorMapIn(vendor="Huntress", counted=[fin.CountedRefIn(source="halopsa", item="Huntress EDR"), fin.CountedRefIn(source="halopsa", item="Huntress EDR")]), req, user, db))
    got = await with_db(w.owner, lambda db: add_on_by_month(db, w.owner, SNAP, ["2026-09", "2026-10"]))
    # September: Acme had 30 and Birch 30 (Birch has no history, so its current 30): 120.00 split in half. October: 10 and 30 of 80.00.
    assert got["2026-09"] == {"acmedentalinc": D("60.00"), "birchlaw": D("60.00")}
    assert got["2026-10"] == {"acmedentalinc": D("20.00"), "birchlaw": D("60.00")}
    again = await with_db(w.owner, lambda db: feed.report_core_feed_vendor_costs("tok", feed.VendorCostsIn(months=[cost_month("2026-10", ("5500", "Huntress", 40.0))]), db))
    assert again.rows == 1
    new = await with_db(w.owner, lambda db: add_on_by_month(db, w.owner, SNAP, ["2026-09", "2026-10"]))
    assert new["2026-10"] == {"acmedentalinc": D("10.00"), "birchlaw": D("30.00")} and new["2026-09"] == got["2026-09"], "October was replaced, September stayed"


async def test_the_software_overview_lists_the_vendors_the_counts_to_choose_from_and_the_cost_of_one_license(world):
    w = world
    user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="hal@x")
    req = SimpleNamespace(client=None, headers={})
    await with_db(w.owner, lambda db: feed.report_core_feed_vendor_costs("tok", feed.VendorCostsIn(months=[cost_month("2026-10", ("5500", "Huntress", 80.0), ("5500", "Lonely Vendor", 5.0), ("5100", "Ninja", 10.0))]), db))

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=w.owner, payload=SNAP))
        await db.commit()

    await with_db(w.owner, ingest)
    before = await with_db(w.owner, lambda db: fin.software_costs(user, db))
    assert before["have_costs"] and before["latest_month"] == "2026-10"
    assert [(v["vendor"], v["account"], v["mapped"]) for v in before["vendors"]] == [("Huntress", "5500", []), ("Lonely Vendor", "5500", []), ("Ninja", "5100", [])], "add-on first, biggest first"
    assert {"source": "halopsa", "item": "Huntress EDR"} in before["counted_items"]
    await with_db(w.owner, lambda db: fin.save_vendor_map(fin.VendorMapIn(vendor="Huntress", counted=[fin.CountedRefIn(source="halopsa", item="Huntress EDR")]), req, user, db))
    after = await with_db(w.owner, lambda db: fin.software_costs(user, db))
    huntress = next(v for v in after["vendors"] if v["vendor"] == "Huntress")
    assert huntress["mapped"] == [{"source": "halopsa", "item": "Huntress EDR"}] and huntress["licenses"] == 40 and huntress["per_license"] == D("2.0000")
    await with_db(w.owner, lambda db: fin.save_vendor_map(fin.VendorMapIn(vendor="Huntress", counted=[]), req, user, db))
    cleared = await with_db(w.owner, lambda db: fin.software_costs(user, db))
    assert next(v for v in cleared["vendors"] if v["vendor"] == "Huntress")["mapped"] == []


async def test_a_vendor_not_billed_in_the_newest_month_still_shows_its_licenses_for_its_own_latest_month(world):
    w = world
    user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="hal@x")
    req = SimpleNamespace(client=None, headers={})
    await with_db(w.owner, lambda db: feed.report_core_feed_vendor_costs("tok", feed.VendorCostsIn(months=[cost_month("2026-09", ("5500", "Huntress", 120.0)), cost_month("2026-10", ("5500", "Other Vendor", 5.0))]), db))

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=w.owner, payload=SNAP))
        await db.commit()

    await with_db(w.owner, ingest)
    await with_db(w.owner, lambda db: fin.save_vendor_map(fin.VendorMapIn(vendor="Huntress", counted=[fin.CountedRefIn(source="halopsa", item="Huntress EDR")]), req, user, db))
    out = await with_db(w.owner, lambda db: fin.software_costs(user, db))
    huntress = next(v for v in out["vendors"] if v["vendor"] == "Huntress")
    assert huntress["latest_month"] == "2026-09" and huntress["licenses"] == 60 and huntress["per_license"] == D("2.0000"), "September: Acme 30 and Birch 30 held"


async def test_support_and_maintenance_bills_are_split_by_the_counts_chosen_for_their_vendor_and_not_mixed_with_add_on(world):
    from app.services.addon_loader import support_by_month

    w = world
    user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="hal@x")
    req = SimpleNamespace(client=None, headers={})
    await with_db(w.owner, lambda db: feed.report_core_feed_vendor_costs("tok", feed.VendorCostsIn(months=[cost_month("2026-09", ("5100", "Huntress", 120.0), ("5500", "Addon Co", 50.0))]), db))

    async def ingest(db):
        db.add(FinanceProfitSnapshot(tenant_id=w.owner, payload=SNAP))
        await db.commit()

    await with_db(w.owner, ingest)
    await with_db(w.owner, lambda db: fin.save_vendor_map(fin.VendorMapIn(vendor="Huntress", counted=[fin.CountedRefIn(source="halopsa", item="Huntress EDR")]), req, user, db))
    got = await with_db(w.owner, lambda db: support_by_month(db, w.owner, SNAP, ["2026-09"]))
    assert got == {"2026-09": {"acmedentalinc": D("60.00"), "birchlaw": D("60.00")}}, "September: 30 and 30 held, split of the 5100 bill only"
    overview = await with_db(w.owner, lambda db: fin.software_costs(user, db))
    huntress = next(v for v in overview["vendors"] if v["vendor"] == "Huntress")
    assert huntress["account"] == "5100" and huntress["licenses"] == 60 and huntress["per_license"] == D("2.0000")

