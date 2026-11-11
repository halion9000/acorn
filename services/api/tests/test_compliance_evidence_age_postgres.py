"""The compliance posture report's evidence age, on a REAL Postgres: only ACCEPTED evidence counts, the NEWEST accepted piece of a control decides its age, and another tenant's evidence is never read.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.compliance import compliance_report
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
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"e-{t.hex[:10]}"})

        async def evidence(tenant, control, status, days_ago):
            when = NOW - timedelta(days=days_ago)
            await s.execute(
                text(
                    "insert into aisoc_compliance_evidence (id, tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, status, created_at) "
                    "values (:i, :t, 'SOC2', :c, 'policy', 'x', '{}'::jsonb, :w, :st, :w)"
                ),
                {"i": uuid.uuid4(), "t": tenant, "c": control, "st": status, "w": when},
            )

        await evidence(a, "CC1.1", "accepted", 500)  # old ...
        await evidence(a, "CC1.1", "accepted", 20)  # ... but refreshed: not stale
        await evidence(a, "CC1.2", "accepted", 400)  # stale
        await evidence(a, "CC1.2", "pending", 2)  # a pending piece does not refresh it
        await evidence(a, "CC1.3", "rejected", 900)  # never accepted: no age at all
        await evidence(b, "CC1.4", "accepted", 2000)  # another tenant's
        await s.commit()
        s.info.update(a=a, b=b)
        yield s
        await off(s)
        await s.execute(text("delete from aisoc_compliance_evidence where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


async def test_the_report_names_the_controls_past_a_year_and_the_oldest_age(world):
    s = world
    await off(s)
    out = await compliance_report(db=s, user=SimpleNamespace(tenant_id=s.info["a"]), tenant=s.info["a"], framework="SOC2")
    soc2 = out[0]
    assert soc2.controls_covered == ["CC1.1", "CC1.2"]
    assert soc2.controls_stale == ["CC1.2"], "CC1.1 was refreshed 20 days ago; CC1.3 was never accepted; the pending piece does not count"
    assert soc2.oldest_evidence_days == 400, "not the 2000 days of another tenant, not the 900 of rejected evidence"


async def test_a_tenant_with_no_accepted_evidence_has_no_age(world):
    s = world
    await off(s)
    out = await compliance_report(db=s, user=SimpleNamespace(tenant_id=uuid.uuid4()), tenant=uuid.uuid4(), framework="SOC2")
    assert out[0].controls_stale == [] and out[0].oldest_evidence_days is None
