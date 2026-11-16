"""The Metrics page routes read what CORE stored: empty until CORE sends, then the page worked out from it. Against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import metrics_pages as ep
from app.db.rls import set_rls_context
from app.models.metric_dataset import MetricDataset
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)

W1, W2 = "2026-10-26", "2026-11-02"
STAFF = {
    "weeks": [W1, W2],
    "rows": [
        {
            "week": W1,
            "agent_id": "40",
            "engineer": "Dan",
            "team": "Pod 1",
            "labor_hours": 30,
            "weekly_utilization": 70,
            "days_worked": 5,
            "closed": 31,
            "ticket_updates": 20,
            "total_calls": 10,
            "total_call_time": 300,
            "surveys": {"total_surveys": 2, "survey_sum": 9},
        },
        {
            "week": W2,
            "agent_id": "40",
            "engineer": "Dan",
            "team": "Pod 1",
            "labor_hours": 12,
            "weekly_utilization": 40,
            "days_worked": 3,
            "closed": 9,
            "ticket_updates": 12,
            "total_calls": 2,
            "total_call_time": 30,
        },
    ],
}


@pytest.fixture
async def world():
    owner, child = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'owner', :s)"), {"i": owner, "s": f"mp-{owner.hex[:8]}"})
        await conn.execute(
            text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, 'Acme Dental', :s, :p)"),
            {"i": child, "s": f"mp-{child.hex[:8]}", "p": owner},
        )
        await conn.execute(
            text(
                "insert into client_license_counts (tenant_id, source, item, unit, count) values (:c, 'm365', 'Business Premium', 'user', 12)"
            ),
            {"c": child},
        )
    yield SimpleNamespace(owner=owner, child=child, user=SimpleNamespace(tenant_id=owner, user_id=None))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from metric_datasets where tenant_id = :t"), {"t": owner})
        await conn.execute(text("delete from client_license_counts where tenant_id = :t"), {"t": child})
        for tid in (child, owner):
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_a_staff_page_is_empty_until_core_sends_then_worked_out_from_what_was_stored(world):
    empty = await with_db(world.owner, lambda db: ep.staff_metrics(world.user, db, 3, None))
    assert empty["received_at"] is None and empty["weeks"] == [] and empty["members"] == []

    async def store(db):
        db.add(MetricDataset(tenant_id=world.owner, key="staff-weekly", payload=STAFF))
        await db.commit()

    await with_db(world.owner, store)
    sm = await with_db(world.owner, lambda db: ep.staff_metrics(world.user, db, 1, None))
    assert sm["received_at"] is not None and [(w["week"], w["utilization"]) for w in sm["weeks"]] == [(W1, 70.0), (W2, 40.0)]
    sc = await with_db(world.owner, lambda db: ep.scorecard(world.user, db, 1, "Dan"))
    assert [(p["engineer"], p["average"]) for p in sc["people"]] == [("Dan", 3.4)] and sc["detail"]["weeks"][1]["score"] == 4.3
    assert (await with_db(world.owner, lambda db: ep.pods(world.user, db, 1)))["pods"][0]["pod"] == "Pod 1"
    assert (await with_db(world.owner, lambda db: ep.ticket_updates(world.user, db, 1, ["Dan"])))["rows"][0]["total"] == 32
    nothing = await with_db(world.owner, lambda db: ep.dialpad(world.user, db, 1, None))
    assert nothing["received_at"] is None, "the Dialpad data has not been sent"


@needs_pg
@pytest.mark.asyncio
async def test_monthly_licensing_lists_each_clients_counts_by_item(world):
    out = await with_db(world.owner, lambda db: ep.monthly_licensing(world.user, db, None))
    assert out["as_of"] == "now"
    assert [(c["client"], c["counts"]) for c in out["clients"]] == [("Acme Dental", {"m365|Business Premium": 12})]
    assert [(i["key"], i["total"]) for i in out["items"]] == [("m365|Business Premium", 12)]
    past = await with_db(world.owner, lambda db: ep.monthly_licensing(world.user, db, "2025-01"))
    assert past["clients"] == [], "nothing was counted that early"


@needs_pg
@pytest.mark.asyncio
async def test_core_feed_keeps_one_row_per_dataset_replaces_it_and_refuses_an_unknown_key_or_an_oversize_one(world):
    from app.api.v1.endpoints import inbox_core_feed as feed
    from fastapi import HTTPException

    keep = lambda key, data: with_db(
        world.owner, lambda db: feed._keep_metric_dataset(db, world.owner, key, feed.MetricDatasetIn(data=data))
    )  # noqa: E731
    first = await keep("staff-weekly", {"weeks": [W1], "rows": [{"week": W1, "engineer": "Dan"}]})
    assert first.model_dump() == {"key": "staff-weekly", "rows": 2}
    await keep("staff-weekly", {"weeks": [], "rows": [{"week": W2, "engineer": "Vic"}]})
    stored = await with_db(
        world.owner, lambda db: db.execute(text("select key, payload from metric_datasets where tenant_id = :t"), {"t": world.owner})
    )
    rows = stored.all()
    assert len(rows) == 1 and rows[0][1]["rows"][0]["engineer"] == "Vic", "the second send replaced the first"
    with pytest.raises(HTTPException) as bad:
        await keep("not-a-dataset", {"rows": []})
    assert bad.value.status_code == 404
    with pytest.raises(HTTPException) as big:
        await keep("ticket-detail", {"rows": [0] * (feed._MAX_DATASET_ROWS + 1)})
    assert big.value.status_code == 413
