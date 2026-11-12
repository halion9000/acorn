"""The same alert at other clients, on a REAL Postgres: only the caller's own organization and its clients, only the same exact title in the last 24 hours, never the tenant the alert is in, and nothing for
a client looking at its own alert. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.alerts import same_alert_at_other_clients
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
NOW = datetime.now(UTC)
TITLE = "Phishing link clicked"
CHECK_TITLE = "Microsoft Defender finds vulnerabilities with a known exploit on this client's devices"
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tag = uuid.uuid4().hex[:10]
    t = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "other_parent", "stranger")}
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for key, tid in t.items():
            parent = t["parent"] if key in ("acme", "birch") else (t["other_parent"] if key == "stranger" else None)
            await s.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                {"i": tid, "n": key, "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
            )
        ids: dict[str, uuid.UUID] = {}

        async def alert(key, tenant, title=TITLE, status="new", hours_ago=2.0, raw="{}"):
            ids[key] = uuid.uuid4()
            created = NOW - timedelta(hours=hours_ago)
            await s.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, raw_event, enrichment_data, created_at, updated_at) "
                    "values (:i, :t, :title, 'high', :st, 50, '[]'::jsonb, cast(:raw as jsonb), '{}'::jsonb, :c, :c)"
                ),
                {"i": ids[key], "t": t[tenant], "title": title, "st": status, "c": created, "raw": raw},
            )

        await alert("this", "acme", hours_ago=1)
        await alert("acme_again", "acme", hours_ago=3)
        await alert("birch_old", "birch", hours_ago=6)
        await alert("birch_new", "birch", hours_ago=0.5)
        await alert("birch_yesterday", "birch", hours_ago=30)
        await alert("birch_hidden", "birch", status="suppressed")
        await alert("birch_other_title", "birch", title="Something else")
        await alert("parent_one", "parent", hours_ago=4)
        await alert("stranger_one", "stranger")
        check = '{"source": "aisoc-checks", "check": "cipp_defender_vulnerabilities"}'
        await alert("check_acme", "acme", title=CHECK_TITLE, raw=check)
        await alert("check_birch", "birch", title=CHECK_TITLE, raw=check)
        await s.commit()
        s.info.update(t=t, ids=ids)
        yield s
        await off(s)
        await s.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in t.values()]})
        await s.execute(
            text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"),
            {"t": [str(x) for x in t.values()]},
        )
        await s.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in t.values()]})
        await s.commit()
    await engine.dispose()


async def test_the_parent_sees_the_same_title_at_its_other_tenants_in_the_last_day_only(world):
    s = world
    await off(s)
    out = await same_alert_at_other_clients(s.info["ids"]["this"], SimpleNamespace(tenant_id=s.info["t"]["parent"]), s)
    assert (
        out["total"] == 3 and out["client_count"] == 2
    ), "not Acme's own, not 30 hours old, not hidden, not another title, not a stranger's"
    birch, own = out["clients"]
    assert birch["name"] == "birch" and birch["count"] == 2 and birch["newest_alert_id"] == str(s.info["ids"]["birch_new"])
    assert own["name"] == "parent" and own["count"] == 1 and own["newest_alert_id"] == str(s.info["ids"]["parent_one"])


async def test_a_posture_check_alert_is_never_called_a_campaign_though_the_same_check_failed_at_another_client(world):
    s = world
    await off(s)
    out = await same_alert_at_other_clients(s.info["ids"]["check_acme"], SimpleNamespace(tenant_id=s.info["t"]["parent"]), s)
    assert (out["total"], out["client_count"], out["clients"]) == (0, 0, [])


async def test_a_client_looking_at_its_own_alert_is_told_nothing_about_anyone_else(world):
    s = world
    await off(s)
    out = await same_alert_at_other_clients(s.info["ids"]["this"], SimpleNamespace(tenant_id=s.info["t"]["acme"]), s)
    assert out == {"window_hours": 24, "total": 0, "client_count": 0, "clients": []}


async def test_an_alert_the_caller_cannot_see_is_a_404(world):
    s = world
    await off(s)
    for alert_id in (uuid.uuid4(), s.info["ids"]["stranger_one"]):
        with pytest.raises(HTTPException) as err:
            await same_alert_at_other_clients(alert_id, SimpleNamespace(tenant_id=s.info["t"]["parent"]), s)
        assert err.value.status_code == 404
