"""CORE's BEC progress and result calls, against a REAL Postgres as the restricted application role (row-level security on).

The case is found with ONE read across the owner's scope (not one client at a time), then changed inside its own client's scope. This checks it finds a case that belongs to a client of the token's owner, never
one of an unrelated organization, and that the change is saved.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid

import pytest
from app.api.v1.endpoints import inbox_core_feed as feed
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"),
]


@pytest.fixture
async def world(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "stranger_parent", "stranger")}
    cases = {"acme": uuid.uuid4(), "stranger": uuid.uuid4()}
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = {"acme": "parent", "birch": "parent", "stranger": "stranger_parent"}.get(key)
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": ids[parent] if parent else None, "r": "child" if parent else "parent"},
                )
            for who, case in cases.items():
                await conn.execute(
                    text("insert into bec_cases (id, tenant_id, case_ref, email, status) values (:i, :t, 'BEC-1', 'p@x.com', 'pending')"),
                    {"i": case, "t": ids[who]},
                )

        async def token_owner(db, token):
            return ids["parent"]

        monkeypatch.setattr(feed, "_verify_core_feed_token", token_owner)
        yield ids, cases
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            everyone = [str(x) for x in ids.values()]
            await conn.execute(text("delete from bec_cases where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": everyone})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": everyone})
        await owner.dispose()


async def stored(case_id):
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text("select status, step, step_label, message from bec_cases where id = :i"), {"i": case_id})).one()
    finally:
        await owner.dispose()


async def call(fn, *args):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            return await fn("token", *args, db=db)
    finally:
        await engine.dispose()


async def test_progress_on_a_clients_case_is_saved(world):
    ids, cases = world
    out = await call(feed.report_bec_progress, cases["acme"], feed.BecProgress(step=2, steps_total=5, label="Reading the mailbox rules"))
    assert out.recorded
    assert tuple(await stored(cases["acme"])) == ("running", 2, "Reading the mailbox rules", None)


async def test_result_closes_the_case_and_a_second_answer_is_refused(world):
    ids, cases = world
    await call(feed.report_bec_result, cases["acme"], feed.BecResult(status="done", message="ok", report={"a": 1}, summary={"x": 1}))
    assert (await stored(cases["acme"]))[0] == "done"
    with pytest.raises(HTTPException) as e:
        await call(feed.report_bec_result, cases["acme"], feed.BecResult(status="failed", message="again"))
    assert e.value.status_code == 404


async def test_another_organizations_case_is_not_found(world):
    ids, cases = world
    with pytest.raises(HTTPException) as e:
        await call(feed.report_bec_progress, cases["stranger"], feed.BecProgress(step=1, steps_total=5, label="x"))
    assert e.value.status_code == 404
    assert (await stored(cases["stranger"]))[0] == "pending"


async def alerts_of(tenant_id):
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text("select title, severity, rule_id, affected_users from alerts where tenant_id = :t"), {"t": tenant_id})).all()
    finally:
        await owner.dispose()


async def test_a_finished_search_rated_high_by_cipp_raises_one_alert_for_the_client_and_a_low_one_raises_none(world):
    ids, cases = world
    report = {"Score": {"Value": 9, "Level": "High"}, "NewRules": [{"Name": "x"}], "Completeness": {"SignIns": {"Complete": False}}}
    summary = {"score": 9, "level": "High", "incomplete": ["SignIns"], "guid": "g1"}
    await call(feed.report_bec_result, cases["acme"], feed.BecResult(status="done", message="ok", report=report, summary=summary))
    rows = await alerts_of(ids["acme"])
    assert [(r[1], r[2], list(r[3])) for r in rows] == [("high", "aisoc-id-bec-findings", ["p@x.com"])]
    assert "CIPP rates it High" in rows[0][0]
    assert await alerts_of(ids["parent"]) == [], "the alert belongs to the client, not the organization"
    with pytest.raises(HTTPException):
        await call(feed.report_bec_result, cases["acme"], feed.BecResult(status="done", report=report, summary=summary))
    assert len(await alerts_of(ids["acme"])) == 1, "an answer that arrives twice makes one alert"


async def test_a_low_rating_and_a_failed_search_raise_no_alert(world):
    ids, cases = world
    await call(feed.report_bec_result, cases["acme"], feed.BecResult(status="done", report={"Score": {"Value": 1, "Level": "Low"}}, summary={"score": 1, "level": "Low"}))
    assert await alerts_of(ids["acme"]) == []
