"""Every client's counts read in one statement, against a REAL Postgres as the restricted application role: the organization's clients only, never another organization's.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import billing
from app.db.rls import set_rls_context
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


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "other_parent", "stranger")}
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = ids["parent"] if key in ("acme", "birch") else (ids["other_parent"] if key == "stranger" else None)
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            for who, item, count, available in (
                ("acme", "Business Premium", 50, 5),
                ("acme", "Exchange Online", 10, 0),
                ("birch", "E3", 20, 12),
                ("stranger", "Secret licence", 99, 90),
            ):
                await conn.execute(
                    text(
                        "insert into client_license_counts (tenant_id, source, item, unit, count, available, first_seen_at, updated_at) "
                        "values (:t, 'm365', :i, 'licence', :c, :a, now(), now())"
                    ),
                    {"t": ids[who], "i": item, "c": count, "a": available},
                )
        yield ids
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            t = [str(x) for x in ids.values()]
            await conn.execute(text("delete from client_license_counts where tenant_id = any(cast(:t as uuid[]))"), {"t": t})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": t})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": t})
        await owner.dispose()


async def as_owner(tenant_id, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant_id)
            return await work(db)
    finally:
        await engine.dispose()


async def test_the_counts_of_every_client_come_back_together_and_only_this_organizations(world):
    counts, names = await as_owner(world["parent"], lambda db: billing._all_client_counts(db, world["parent"]))
    assert set(counts) == {world["acme"], world["birch"]}
    assert sorted(r["item"] for r in counts[world["acme"]]) == ["Business Premium", "Exchange Online"]
    assert [r["item"] for r in counts[world["birch"]]] == ["E3"]
    assert "Secret licence" not in str(counts)


async def test_the_licence_waste_report_lists_the_unassigned_licences_of_this_organizations_clients_only(world):
    out = await as_owner(world["parent"], lambda db: billing.licence_waste(SimpleNamespace(tenant_id=world["parent"]), db, 1, 500))
    assert [(r.item, r.unassigned) for r in out.rows] == [("E3", 12), ("Business Premium", 5)]
    assert (out.total_bought, out.total_unassigned, out.clients) == (70, 17, 2)


async def test_the_other_organization_sees_its_own_client_only(world):
    out = await as_owner(
        world["other_parent"], lambda db: billing.licence_waste(SimpleNamespace(tenant_id=world["other_parent"]), db, 1, 500)
    )
    assert [(r.item, r.unassigned) for r in out.rows] == [("Secret licence", 90)]


async def test_the_start_of_each_disagreement_is_read_for_all_clients_at_once_from_only_the_history_of_the_lines_in_play(world):
    from datetime import UTC, datetime, timedelta

    from app.services.license_counts import disagreement_since

    BILLED_SOURCE = billing.BILLED_SOURCE

    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    t0 = now - timedelta(days=40)
    owner = create_async_engine(PG_URL)
    rows = [  # (client, source, item, count, previous, days ago): the invoice line and the tool count it is checked against, then a scanner count that flaps every day
        ("acme", BILLED_SOURCE, "Endpoint protection", 10, None, 40),
        ("acme", "huntress", "Agents", 10, None, 40),
        ("acme", "huntress", "Agents", 8, 10, 15),
    ] + [("acme", "auvik", "Discovered devices", 100 + d, 99 + d, d) for d in range(1, 30)]
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for who, source, item, count, prev, days in rows:
                await conn.execute(
                    text("insert into client_license_history (tenant_id, source, item, unit, count, previous_count, observed_at) values (:t, :s, :i, 'other', :c, :p, :o)"),
                    {"t": world[who], "s": source, "i": item, "c": count, "p": prev, "o": now - timedelta(days=days)},
                )
            for source, item, count in ((BILLED_SOURCE, "Endpoint protection", 10), ("huntress", "Agents", 8)):
                await conn.execute(
                    text("insert into client_license_counts (tenant_id, source, item, unit, count, available, first_seen_at, updated_at) values (:t, :s, :i, 'other', :c, 0, :f, now())"),
                    {"t": world["acme"], "s": source, "i": item, "c": count, "f": t0},
                )
        lines = {world["acme"]: [("Endpoint protection", [{"source": "huntress", "item": "Agents"}])]}
        got = await as_owner(world["parent"], lambda db: billing._disagreement_starts_many(db, lines, now))
        history = {(BILLED_SOURCE, "Endpoint protection"): [{"observed_at": now - timedelta(days=40), "count": 10}], ("huntress", "Agents"): [{"observed_at": now - timedelta(days=40), "count": 10}, {"observed_at": now - timedelta(days=15), "count": 8}]}
        current = {(BILLED_SOURCE, "Endpoint protection"): (10, t0), ("huntress", "Agents"): (8, t0)}
        tracking = {BILLED_SOURCE: t0, "huntress": t0}
        expected = disagreement_since((BILLED_SOURCE, "Endpoint protection"), [("huntress", "Agents")], history, current, tracking, now)
        assert got == {world["acme"]: {"Endpoint protection": expected}}
        assert (now - got[world["acme"]]["Endpoint protection"][0]).days == 15, "the line has not matched since the count of the tool dropped 15 days ago"
        assert await as_owner(world["parent"], lambda db: billing._disagreement_starts_many(db, {}, now)) == {}
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from client_license_history where tenant_id = :t"), {"t": world["acme"]})
        await owner.dispose()
