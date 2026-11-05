"""A case made from an alert held by one of the caller's client tenants, against a REAL Postgres (opt in with AISOC_TEST_PG_URL, a DISPOSABLE, fully migrated database).

An MSSP parent works its clients' alerts, which are stored under the client. "Promote alert to case" failed with "One or more alerts were not found" because the ownership check only knew the caller's own tenant.
"""

import os
import uuid

import pytest
from app.api.v1.deps import CurrentUser
from app.api.v1.endpoints.cases import AddAlertsRequest, CreateCaseRequest, add_alerts, create_case
from app.db.rls import set_rls_context
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:8]
    ids = {k: uuid.uuid4() for k in ("msp", "client", "stranger")}
    alerts = {"client": uuid.uuid4(), "stranger": uuid.uuid4(), "msp": uuid.uuid4()}
    engine = create_async_engine(PG_URL)
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for key, tid in ids.items():
            await c.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                {"i": tid, "n": f"cfa-{key}-{tag}", "s": f"cfa-{key}-{tag}", "p": ids["msp"] if key == "client" else None, "r": "child" if key == "client" else "parent"},
            )
        for key, aid in alerts.items():
            await c.execute(
                text("insert into alerts (id, tenant_id, title, severity, status, created_at, updated_at) values (:a, :t, 'x', 'high', 'new', now(), now())"),
                {"a": aid, "t": ids[key]},
            )
    yield ids, alerts
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(text("set local session_replication_role = replica"))
        await c.execute(text("delete from aisoc_cases where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await c.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await c.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
    await engine.dispose()


def user(tenant_id: uuid.UUID) -> CurrentUser:
    return CurrentUser(user_id=uuid.uuid4(), tenant_id=tenant_id, role="admin", email="hal@example.com")


async def run(owner: uuid.UUID, work):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            return await work(db)
    finally:
        await engine.dispose()


async def case_link(alert_id: uuid.UUID):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await c.execute(text("select case_id from alerts where id = :a"), {"a": alert_id})).scalar_one()
    finally:
        await engine.dispose()


async def test_the_parent_can_make_a_case_from_a_client_alert_and_the_alert_points_back_at_it(world):
    ids, alerts = world
    out = await run(ids["msp"], lambda db: create_case(body=CreateCaseRequest(title="from a client alert", alert_ids=[alerts["client"]]), db=db, user=user(ids["msp"])))
    assert out.alert_ids == [alerts["client"]]
    assert await case_link(alerts["client"]) == out.id, "the client's alert now points at the case"


async def test_a_parent_can_mix_its_own_alert_and_a_clients_and_link_both(world):
    ids, alerts = world
    out = await run(ids["msp"], lambda db: create_case(body=CreateCaseRequest(title="mixed", alert_ids=[alerts["msp"], alerts["client"]]), db=db, user=user(ids["msp"])))
    assert await case_link(alerts["msp"]) == out.id and await case_link(alerts["client"]) == out.id


async def test_somebody_elses_alert_is_still_not_found_and_nothing_is_linked(world):
    ids, alerts = world
    with pytest.raises(HTTPException) as exc:
        await run(ids["msp"], lambda db: create_case(body=CreateCaseRequest(title="not mine", alert_ids=[alerts["client"], alerts["stranger"]]), db=db, user=user(ids["msp"])))
    assert exc.value.status_code == 404 and exc.value.detail == "One or more alerts were not found."
    assert await case_link(alerts["client"]) is None and await case_link(alerts["stranger"]) is None


async def test_a_client_cannot_cite_its_parents_alert(world):
    ids, alerts = world
    with pytest.raises(HTTPException) as exc:
        await run(ids["client"], lambda db: create_case(body=CreateCaseRequest(title="up the tree", alert_ids=[alerts["msp"]]), db=db, user=user(ids["client"])))
    assert exc.value.status_code == 404


async def test_adding_a_client_alert_to_an_existing_case_works_too(world):
    ids, alerts = world
    made = await run(ids["msp"], lambda db: create_case(body=CreateCaseRequest(title="empty", alert_ids=[]), db=db, user=user(ids["msp"])))
    out = await run(ids["msp"], lambda db: add_alerts(case_id=str(made.id), body=AddAlertsRequest(alert_ids=[alerts["client"]]), db=db, user=user(ids["msp"])))
    assert out.alert_ids == [alerts["client"]]
    assert await case_link(alerts["client"]) == made.id
