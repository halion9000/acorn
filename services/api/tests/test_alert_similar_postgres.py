"""Similar alerts on a REAL Postgres: the same client only, within 30 days, matched by rule, exact title, or a shared host, user or address, with the reasons.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.alerts import similar_alerts
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
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"s-{t.hex[:10]}"})
        ids: dict[str, uuid.UUID] = {}

        async def alert(key, tenant, title="Impossible travel", rule="rule-1", hosts=(), users=(), ips=(), days_ago=1, status="new"):
            ids[key] = uuid.uuid4()
            created = NOW - timedelta(days=days_ago)
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, rule_id, affected_hosts, affected_users, affected_ips, raw_event, enrichment_data, created_at, updated_at, event_time, first_seen, last_seen) "
                    "values (:i, :t, :title, 'high', :st, 50, :rule, cast(:h as jsonb), cast(:u as jsonb), cast(:ip as jsonb), '{}'::jsonb, '{}'::jsonb, :c, :c, :c, :c, :c)"
                ),
                {"i": ids[key], "t": tenant, "title": title, "st": status, "rule": rule, "h": json.dumps(list(hosts)), "u": json.dumps(list(users)), "ip": json.dumps(list(ips)), "c": created},
            )

        await alert("this", a, hosts=["PC-1"], users=["ann@x.com"], ips=["1.1.1.1"])
        await alert("rule_title", a, days_ago=2)
        await alert("host_only", a, title="Other thing", rule="rule-2", hosts=["PC-1"], days_ago=3)
        await alert("user_only", a, title="User thing", rule="rule-3", users=["ann@x.com"], days_ago=4)
        await alert("ip_only", a, title="Ip thing", rule="rule-4", ips=["1.1.1.1"], days_ago=5)
        await alert("old", a, days_ago=90)
        await alert("unrelated", a, title="Nothing alike", rule="rule-9", hosts=["PC-9"])
        await alert("suppressed", a, status="suppressed")
        await alert("other_client", b, hosts=["PC-1"])
        await s.commit()
        s.info.update(a=a, b=b, ids=ids)
        yield s
        await off(s)
        await s.execute(text("delete from alerts where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


async def test_only_this_clients_recent_alerts_that_share_the_rule_title_host_user_or_address_are_listed_best_first(world):
    s = world
    await off(s)
    ids = s.info["ids"]
    out = await similar_alerts(ids["this"], SimpleNamespace(tenant_id=s.info["a"]), s)
    got = [(a["id"], a["why"]) for a in out["alerts"]]
    assert [g[0] for g in got] == [str(ids["rule_title"]), str(ids["host_only"]), str(ids["user_only"]), str(ids["ip_only"])]
    assert got[0][1] == ["same rule", "same title"]
    assert got[1][1] == ["same host: pc-1"] and got[2][1] == ["same user: ann@x.com"] and got[3][1] == ["same ip: 1.1.1.1"]
    listed = {g[0] for g in got}
    for left_out in ("this", "old", "unrelated", "suppressed", "other_client"):
        assert str(ids[left_out]) not in listed, left_out
    assert out["window_days"] == 30


async def test_an_alert_with_nothing_to_match_on_lists_nothing_and_an_unknown_alert_is_a_404(world):
    s = world
    await off(s)
    bare = uuid.uuid4()
    await s.execute(
        text(
            "insert into alerts (id, tenant_id, title, severity, status, priority, rule_id, affected_hosts, affected_users, affected_ips, raw_event, enrichment_data, created_at, updated_at, event_time, first_seen, last_seen) "
            "values (:i, :t, '', 'low', 'new', 50, null, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, :c, :c, :c, :c, :c)"
        ),
        {"i": bare, "t": s.info["a"], "c": NOW},
    )
    await s.commit()
    out = await similar_alerts(bare, SimpleNamespace(tenant_id=s.info["a"]), s)
    assert out["alerts"] == []
    with pytest.raises(HTTPException) as err:
        await similar_alerts(uuid.uuid4(), SimpleNamespace(tenant_id=s.info["a"]), s)
    assert err.value.status_code == 404
