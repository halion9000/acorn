"""The noise report on a REAL Postgres: counts per rule for one client or the whole organization, tickets and old alerts left out of the quiet count, and no stranger's alerts.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.alerts import noise_report
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    owner, acme, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t, parent in ((owner, None), (acme, owner), (stranger, None)):
            await s.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, 'x', :s, :p)"), {"t": t, "s": f"n-{t.hex[:10]}", "p": parent})

        async def alert(tenant, rule, status, ticket=False, days_ago=2, title="T"):
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, rule_name, severity, status, priority, affected_hosts, raw_event, enrichment_data, created_at, updated_at, event_time, first_seen, last_seen) "
                    "values (:i, :t, :ti, :r, 'low', :st, 50, '[]'::jsonb, '{}'::jsonb, cast(:e as jsonb), :c, :c, :c, :c, :c)"
                ),
                {"i": uuid.uuid4(), "t": tenant, "ti": title, "r": rule, "st": status, "e": json.dumps({"tickets": [{"system": "halopsa", "id": "5"}]} if ticket else {}), "c": NOW - timedelta(days=days_ago)},
            )

        for _ in range(3):
            await alert(acme, "Impossible travel", "false_positive")
        await alert(acme, "Impossible travel", "closed", ticket=True)
        await alert(acme, "Impossible travel", "new")
        await alert(acme, "Impossible travel", "false_positive", days_ago=90)
        await alert(acme, "", "suppressed", title="Untitled rule alert")
        await alert(owner, "Impossible travel", "stale")
        await alert(stranger, "Impossible travel", "false_positive")
        await s.commit()
        s.info.update(owner=owner, acme=acme)
        yield s
        await off(s)
        for t in (owner, acme, stranger):
            await s.execute(text("delete from alerts where tenant_id = :t"), {"t": t})
        await s.execute(text("delete from tenants where id in (:a, :b, :c)"), {"a": acme, "b": owner, "c": stranger})
        await s.commit()
    await engine.dispose()


async def test_one_client_counts_its_quiet_alerts_per_rule_leaving_out_tickets_open_alerts_and_old_ones(world):
    s = world
    await off(s)
    out = await noise_report(SimpleNamespace(tenant_id=s.info["owner"]), s, s.info["acme"], 30)
    by = {r["rule"]: r for r in out["rules"]}
    it = by["Impossible travel"]
    assert (it["total"], it["quiet"], it["with_ticket"]) == (5, 3, 1), "three false positives; the ticketed close, the open alert and the 90-day-old one are not quiet or not in range"
    assert by["Untitled rule alert"]["quiet"] == 1, "no rule name: the alert's title stands in"
    assert out["total_alerts"] == 6 and out["days"] == 30 and out["client_id"] == str(s.info["acme"])


async def test_the_whole_organization_adds_its_clients_and_never_a_strangers_and_an_unknown_client_is_a_404(world):
    s = world
    await off(s)
    out = await noise_report(SimpleNamespace(tenant_id=s.info["owner"]), s, None, 30)
    it = next(r for r in out["rules"] if r["rule"] == "Impossible travel")
    assert (it["total"], it["quiet"]) == (6, 4), "the client's five and the owner's own stale one; the stranger's alert is not counted"
    with pytest.raises(HTTPException) as err:
        await noise_report(SimpleNamespace(tenant_id=s.info["owner"]), s, uuid.uuid4(), 30)
    assert err.value.status_code == 404
