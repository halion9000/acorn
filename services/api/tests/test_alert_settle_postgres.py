"""An alert its tool has closed is closed for good only when every HaloPSA ticket on it is closed too, on a REAL Postgres. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from app.api.v1.endpoints.inbox_core_feed import (
    ClosedItem,
    ClosedReport,
    LinkedTicket,
    TicketsItem,
    TicketsReport,
    apply_closed,
    apply_tickets,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


def tk(status, i="1"):
    return {"system": "halopsa", "id": i, "status": status}


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'o', :s)"), {"t": tenant, "s": f"st-{tenant.hex[:10]}"})
        ids = {}

        async def alert(key, status, tickets=None, manual=None):
            ids[key] = uuid.uuid4()
            enrichment = {}
            if tickets is not None:
                enrichment["tickets"] = tickets
            if manual is not None:
                enrichment["manual_tickets"] = manual
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, raw_event, enrichment_data, created_at, updated_at) "
                    "values (:i, :t, :n, 'low', :st, 50, cast(:raw as jsonb), cast(:enr as jsonb), now(), now())"
                ),
                {
                    "i": ids[key],
                    "t": tenant,
                    "n": key,
                    "st": status,
                    "raw": json.dumps({"finding": {"uid": f"huntress:{key}"}}),
                    "enr": json.dumps(enrichment),
                },
            )

        await alert("no_ticket", "new")
        await alert("open_ticket", "new", [tk("In Progress")])
        await alert("closed_ticket", "new", [tk("Closed")])
        await alert("mixed", "new", [tk("Closed", "1")], [tk("Open", "2")])
        await alert("working_closed_ticket", "investigating", [tk("Resolved")])
        await alert("working_no_ticket", "investigating")
        await alert("unknown_status", "new", [{"system": "halopsa", "id": "9"}])
        await s.commit()
        yield s, tenant, ids
        await off(s)
        await s.execute(text("delete from alerts where tenant_id = :t"), {"t": tenant})
        await s.execute(text("delete from tenants where id = :t"), {"t": tenant})
        await s.commit()
    await engine.dispose()


async def state(s, ids):
    await off(s)
    rows = (
        await s.execute(
            text("select id, status, enrichment_data ? 'closed_in_vendor' from alerts where id = any(:i)"), {"i": list(ids.values())}
        )
    ).all()
    by = {r[0]: (r[1], r[2]) for r in rows}
    return {k: by[v] for k, v in ids.items()}


async def test_a_closed_tool_incident_resolves_the_alert_only_when_no_ticket_is_still_open(world):
    s, tenant, ids = world
    await off(s)
    report = ClosedReport(vendor="huntress", closed=[ClosedItem(uid=f"huntress:{k}", state="resolved") for k in ids])
    await apply_closed(s, tenant, report, datetime.now(UTC))
    await s.commit()
    got = await state(s, ids)
    resolved = {k for k, (st, _) in got.items() if st == "resolved"}
    assert (
        resolved == {"no_ticket", "closed_ticket", "working_closed_ticket", "unknown_status"}
    ), "no ticket, a ticket with no status text, or every ticket closed (even for an alert someone was working on); an alert someone is working with no ticket is left to them"
    assert {k for k, (st, noted) in got.items() if st != "resolved" and noted} == {
        "open_ticket",
        "mixed",
        "working_no_ticket",
    }, "the rest stay open but remember the tool closed them"


async def test_the_last_ticket_closing_closes_an_alert_the_tool_already_closed_and_never_one_it_has_not(world):
    s, tenant, ids = world
    await off(s)
    await apply_closed(s, tenant, ClosedReport(vendor="huntress", closed=[ClosedItem(uid="huntress:open_ticket")]), datetime.now(UTC))
    await s.commit()
    assert (await state(s, ids))["open_ticket"][0] == "new"
    report = TicketsReport(
        vendor="huntress",
        items=[
            TicketsItem(uid="huntress:open_ticket", tickets=[LinkedTicket(id="1", status="Closed")]),
            TicketsItem(uid="huntress:unknown_status", tickets=[LinkedTicket(id="9", status="Closed")]),
        ],
    )
    await apply_tickets(s, tenant, report)
    await s.commit()
    got = await state(s, ids)
    assert got["open_ticket"][0] == "resolved", "the tool closed it and now its ticket is closed"
    assert got["unknown_status"][0] == "new", "the tool has not closed this one, so a closed ticket does not close it"
