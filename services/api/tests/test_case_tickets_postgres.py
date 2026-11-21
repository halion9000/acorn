"""A case is always tied to a HaloPSA ticket, against a REAL Postgres (opt in with AISOC_TEST_PG_URL, a DISPOSABLE, fully migrated database).

Covers: a case made from an alert takes the alert's tickets; a ticket CORE reports later for an alert goes on the cases holding it (once); a person links a ticket by number (digits only, once);
a person asks for a new ticket (one request waits at a time) and CORE's report of its number lands on the case.
"""

import os
import uuid

import pytest
from app.api.v1.deps import CurrentUser
from app.api.v1.endpoints.cases import CreateCaseRequest, LinkTicketRequest, create_case, create_ticket_for_case, link_ticket
from app.db.rls import set_rls_context
from app.services import case_tickets
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:8]
    tenant = uuid.uuid4()
    alert_with_ticket, alert_without = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL)
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(
            text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tenant, "n": f"ct-{tag}", "s": f"ct-{tag}"}
        )
        await c.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, enrichment_data, created_at, updated_at) "
                "values (:a, :t, 'x', 'high', 'new', cast(:e as jsonb), now(), now())"
            ),
            {"a": alert_with_ticket, "t": tenant, "e": '{"manual_tickets": [{"system": "halopsa", "id": "4711"}], "tickets": [{"id": "4711"}, {"id": "4712"}]}'},
        )
        await c.execute(
            text("insert into alerts (id, tenant_id, title, severity, status, created_at, updated_at) values (:a, :t, 'y', 'high', 'new', now(), now())"),
            {"a": alert_without, "t": tenant},
        )
    yield tenant, alert_with_ticket, alert_without
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(text("set local session_replication_role = replica"))
        for table in ("vendor_actions", "aisoc_cases", "alerts"):
            await c.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tenant})
        await c.execute(text("delete from tenants where id = :t"), {"t": tenant})
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


def ids_of(refs):
    return sorted(r["id"] for r in refs)


@pytest.mark.asyncio
async def test_a_case_made_from_alerts_takes_their_tickets_and_later_ones_follow(world):
    tenant, with_ticket, without = world
    me = user(tenant)
    made = await run(tenant, lambda db: create_case(CreateCaseRequest(title="From two alerts", alert_ids=[with_ticket, without]), db, me))
    assert ids_of(made.ticket_refs) == ["4711", "4712"]  # the tickets the alert already had, each once
    assert case_tickets.has_ticket(made.ticket_refs)

    # CORE opens a ticket for the other alert: it reaches the case, and reporting it twice changes nothing.
    async def report(db):
        first = await case_tickets.link_ticket_to_cases_of_alert(db, tenant, without, "5001", "ticket rule", __import__("datetime").datetime.now(__import__("datetime").UTC))
        again = await case_tickets.link_ticket_to_cases_of_alert(db, tenant, without, "5001", "ticket rule", __import__("datetime").datetime.now(__import__("datetime").UTC))
        await db.commit()
        return first, again

    assert await run(tenant, report) == (1, 0)
    refs = (await run(tenant, lambda db: db.execute(text("select ticket_refs from aisoc_cases where id = :i"), {"i": made.id}))).scalar_one()
    assert ids_of(refs) == ["4711", "4712", "5001"]


@pytest.mark.asyncio
async def test_a_manual_case_links_a_typed_ticket_and_refuses_what_is_not_a_number(world):
    tenant, _, _ = world
    me = user(tenant)
    made = await run(tenant, lambda db: create_case(CreateCaseRequest(title="By hand", ticket_id="#9001"), db, me))
    assert ids_of(made.ticket_refs) == ["9001"]
    linked = await run(tenant, lambda db: link_ticket(str(made.id), LinkTicketRequest(ticket_id="9002"), db, me))
    assert ids_of(linked.ticket_refs) == ["9001", "9002"]
    again = await run(tenant, lambda db: link_ticket(str(made.id), LinkTicketRequest(ticket_id="9002"), db, me))
    assert ids_of(again.ticket_refs) == ["9001", "9002"]
    with pytest.raises(HTTPException) as e:
        await run(tenant, lambda db: link_ticket(str(made.id), LinkTicketRequest(ticket_id="INC-12"), db, me))
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_asking_for_a_ticket_queues_one_request_and_the_reported_number_lands_on_the_case(world):
    tenant, _, _ = world
    me = user(tenant)
    made = await run(tenant, lambda db: create_case(CreateCaseRequest(title="No ticket yet"), db, me))
    assert made.ticket_refs == [] and not case_tickets.has_ticket(made.ticket_refs)
    first = await run(tenant, lambda db: create_ticket_for_case(str(made.id), db, me))
    second = await run(tenant, lambda db: create_ticket_for_case(str(made.id), db, me))
    assert (first.queued, second.queued) == (True, False)  # pressing it twice makes one request

    async def actions(db):
        return (await db.execute(text("select action, incident_uid, alert_id, status, params from vendor_actions where tenant_id = :t"), {"t": tenant})).all()

    rows = await run(tenant, actions)
    assert len(rows) == 1 and rows[0].action == "create_ticket" and rows[0].alert_id is None and rows[0].status == "pending"
    assert rows[0].incident_uid == f"case-ticket:{made.id}" and rows[0].params["summary"] == "No ticket yet"

    async def reported(db):
        import datetime

        done = await case_tickets.on_ticket_created(db, tenant, rows[0].incident_uid, "7777", datetime.datetime.now(datetime.UTC))
        other = await case_tickets.on_ticket_created(db, tenant, "bec-search:1", "7778", datetime.datetime.now(datetime.UTC))
        await db.commit()
        return done, other

    assert await run(tenant, reported) == (True, False)  # only an action that was for a case is ours
    refs = (await run(tenant, lambda db: db.execute(text("select ticket_refs from aisoc_cases where id = :i"), {"i": made.id}))).scalar_one()
    assert ids_of(refs) == ["7777"]


