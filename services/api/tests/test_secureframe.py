"""Secureframe's report in A.C.O.R.N: what the route accepts, the percentage it shows, and (on a REAL Postgres, AISOC_TEST_PG_URL) that a report replaces the one before it and one organization never reads another's."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import secureframe as sf
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

COUNTS = {"total": 10, "enabled": 8, "passing": 5, "failing": 2, "not_evaluated": 1, "disabled": 2}


def body(**over):
    return {
        "vendor": "secureframe",
        "report": {
            "tests": COUNTS,
            "frameworks": [{"key": "soc2", "name": "SOC 2", "failing": 2, "passing": 5}],
            "failing": [{"title": "MFA on all accounts", "owner": "Dale", "failing_since": "2026-10-01T00:00:00Z", "frameworks": ["soc2"]}],
            "risks": 12,
            "policies": None,
            **over,
        },
    }


def test_a_report_is_accepted_with_unknown_risk_and_policy_counts_kept_as_unknown():
    r = sf.ReportIn.model_validate(body())
    assert r.report.risks == 12 and r.report.policies is None, "a list the key may not read is unknown, not zero"
    assert r.report.failing[0].owner == "Dale"


def test_a_malformed_report_is_refused():
    bad = [
        body(tests={**COUNTS, "failing": -1}),
        body(tests={"total": 1}),
        body(failing=[{"title": ""}]),
        body(failing=[{"title": "x"}] * (sf.MAX_FAILING + 1)),
        {**body(), "vendor": "other"},
        {"report": "no"},
    ]
    for payload in bad:
        with pytest.raises(ValidationError):
            sf.ReportIn.model_validate(payload)


def test_the_passing_share_is_of_the_tests_that_were_evaluated():
    assert sf.passing_percent(sf.TestCounts(**COUNTS)) == pytest.approx(
        71.4, abs=0.05
    ), "5 of the 7 that passed or failed; not evaluated and disabled tests are not in it"
    assert sf.passing_percent(sf.TestCounts(total=3, enabled=0, passing=0, failing=0, not_evaluated=0, disabled=3)) is None


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pg
@pytest.mark.asyncio
async def test_the_latest_report_replaces_the_one_before_and_each_organization_reads_only_its_own(monkeypatch):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    mine, other = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (mine, other):
            await conn.execute(text("insert into tenants (id, name, slug) values (:t, 'sf', :s)"), {"t": t, "s": f"sf-{t.hex[:10]}"})
    try:
        async with AsyncSession(engine) as db:

            async def verify(_db, token):
                return {"mine": mine, "other": other}[token]

            async def adopt(_db, _owner):
                return None

            monkeypatch.setattr(sf, "_verify_core_feed_token", verify)
            monkeypatch.setattr(sf, "adopt_tenant", adopt)
            assert (await sf.report_core_feed_secureframe("mine", sf.ReportIn.model_validate(body()), db)).stored
            newer = body(tests={**COUNTS, "passing": 7, "failing": 0, "not_evaluated": 1}, failing=[])
            await sf.report_core_feed_secureframe("mine", sf.ReportIn.model_validate(newer), db)
            await sf.report_core_feed_secureframe("other", sf.ReportIn.model_validate(body(risks=1)), db)
            view = await sf.secureframe_view(SimpleNamespace(tenant_id=mine), db)
            assert view.report is not None and view.report.tests.failing == 0 and view.report.failing == []
            assert view.report.risks == 12 and view.passing_percent == 100.0 and view.received_at is not None
            assert (
                await sf.secureframe_view(SimpleNamespace(tenant_id=uuid.uuid4()), db)
            ).report is None, "nothing for an organization that never reported"
            rows = (
                await db.execute(text("select count(*) from secureframe_reports where tenant_id = any(:t)"), {"t": [mine, other]})
            ).scalar_one()
            assert rows == 2, "one row per organization, replaced in place"
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from secureframe_reports where tenant_id = any(:t)"), {"t": [mine, other]})
            await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [mine, other]})
        await engine.dispose()
