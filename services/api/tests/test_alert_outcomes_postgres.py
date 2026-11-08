"""What usually happened to earlier alerts of the same kind, on a REAL Postgres: same client and same exact title only, the alert itself and old ones left out, tickets counted from the enrichment data.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.alerts import earlier_outcomes
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
TITLE = "Impossible travel sign-in"
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"o-{t.hex[:10]}"})
        ids: dict[str, uuid.UUID] = {}

        async def alert(key, tenant, title=TITLE, status="resolved", days_ago=5, hours=2, ticket=False, disposition="false_positive"):
            ids[key] = uuid.uuid4()
            created = NOW - timedelta(days=days_ago)
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, raw_event, enrichment_data, disposition, created_at, updated_at, resolved_at) "
                    "values (:i, :t, :title, 'low', :st, 50, '[]'::jsonb, '{}'::jsonb, cast(:enr as jsonb), :d, :c, :c, :r)"
                ),
                {"i": ids[key], "t": tenant, "title": title, "st": status, "enr": json.dumps({"tickets": [{"system": "halopsa", "id": "5"}]} if ticket else {}), "d": disposition if status != "new" else None, "c": created, "r": created + timedelta(hours=hours) if status != "new" else None},
            )

        await alert("this", a, status="new")
        await alert("e1", a, hours=1, ticket=True)
        await alert("e2", a, hours=3)
        await alert("e3", a, status="closed", hours=5, disposition="benign")
        await alert("old", a, days_ago=400)
        await alert("other_title", a, title="Something else")
        await alert("other_client", b)
        await s.commit()
        s.info.update(a=a, b=b, ids=ids)
        yield s
        await off(s)
        await s.execute(text("delete from alerts where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


async def test_only_this_clients_earlier_alerts_with_the_same_title_in_the_window_are_counted(world):
    s = world
    await off(s)
    out = await earlier_outcomes(s.info["ids"]["this"], SimpleNamespace(tenant_id=s.info["a"]), s)
    assert out["total"] == 3 and out["enough"] is True, "not itself, not the 400-day-old one, not another title, not another client"
    assert out["by_status"] == {"resolved": 2, "closed": 1}
    assert out["by_disposition"] == {"false_positive": 2, "benign": 1}
    assert out["with_ticket"] == 1 and out["median_hours_to_finish"] == 3.0 and out["still_open"] == 0


async def test_an_unknown_alert_is_a_404(world):
    s = world
    await off(s)
    with pytest.raises(HTTPException) as err:
        await earlier_outcomes(uuid.uuid4(), SimpleNamespace(tenant_id=s.info["a"]), s)
    assert err.value.status_code == 404
