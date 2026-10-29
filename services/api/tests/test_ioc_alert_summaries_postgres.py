"""The IOC list says what the alerts that name each indicator were about (their titles), from one query for the page, never another tenant's alerts. REAL Postgres (AISOC_TEST_PG_URL)."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from app.api.v1.endpoints.threat_intel import with_alert_summaries
from app.db.rls import set_rls_context
from app.models.threat_intel import ThreatIntelIOC
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    mine, other = uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for t, n in ((mine, "mine"), (other, "other")):
                await conn.execute(
                    text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
                    {"i": t, "n": f"ioc-{n}-{tag}", "s": f"ioc-{n}-{tag}"},
                )
            for aid, tenant, title in (
                (uuid.UUID(int=1), mine, "Endpoint Risk - Suspicious Process Detected"),
                (uuid.UUID(int=2), mine, "Second alert"),
                (uuid.UUID(int=3), mine, "Third alert"),
                (uuid.UUID(int=4), other, "Someone else's alert"),
            ):
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, event_time, first_seen, last_seen) values (:i, :t, :ti, 'medium', 'new', :n, :n, :n)"
                    ),
                    {"i": aid, "t": tenant, "ti": title, "n": now},
                )
        yield mine, other, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(mine), str(other)]})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [mine, other]})
        await engine.dispose()


def ioc(tenant, linked):
    now = datetime.now(UTC)
    return ThreatIntelIOC(
        id=uuid.uuid4(),
        tenant_id=tenant,
        ioc_type="file_hash_sha256",
        value="a" * 64,
        confidence=30,
        severity="info",
        tlp="amber",
        source="alerts",
        is_active=True,
        false_positive=False,
        linked_alerts=linked,
        context={},
        first_seen=now,
        last_seen=now,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_each_indicator_gets_the_titles_of_its_first_two_alerts_and_nothing_from_another_tenant(world):
    mine, _other, engine = world
    db = async_sessionmaker(engine, expire_on_commit=False)()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    await set_rls_context(db, mine)
    rows = [ioc(mine, [uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)]), ioc(mine, None), ioc(mine, [uuid.UUID(int=4)])]
    out = await with_alert_summaries(db, mine, rows)
    await db.close()
    assert [a.title for a in out[0].linked_alert_summaries] == [
        "Endpoint Risk - Suspicious Process Detected",
        "Second alert",
    ], "the first two only"
    assert out[0].linked_alert_summaries[0].severity == "medium"
    assert out[1].linked_alert_summaries == []
    assert out[2].linked_alert_summaries == [], "an alert of another tenant is never named"


@pytest.mark.asyncio
async def test_an_indicator_held_by_the_workspace_names_the_clients_alert_with_its_client_host_and_person(world):
    mine, _other, engine = world
    kid, alert_id = uuid.uuid4(), uuid.UUID(int=77)
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :n, :p, 'child')"),
                {"i": kid, "n": f"Pirkey Barber {tag}", "p": mine},
            )
            await conn.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, affected_hosts, affected_users, event_time, first_seen, last_seen) "
                    "values (:i, :t, 'Malware blocked', 'high', 'new', cast(:h as jsonb), cast(:u as jsonb), :n, :n, :n)"
                ),
                {"i": alert_id, "t": kid, "h": '["", "PC-01"]', "u": '["amy@acme.com"]', "n": now},
            )
        db = async_sessionmaker(engine, expire_on_commit=False)()
        await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        await set_rls_context(db, mine)
        out = await with_alert_summaries(db, mine, [ioc(mine, [alert_id])])
        await db.close()
        (a,) = out[0].linked_alert_summaries
        assert (a.title, a.severity, a.status) == ("Malware blocked", "high", "new")
        assert (a.client, a.host, a.user) == (f"Pirkey Barber {tag}", "PC-01", "amy@acme.com"), "the first host that is not blank"
        assert a.created_at is not None
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from alerts where tenant_id = :t"), {"t": kid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": kid})
