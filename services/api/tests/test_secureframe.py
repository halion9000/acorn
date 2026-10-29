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


REQUIREMENTS = [
    {
        "framework": "CIS_IG1",
        "key": "9.2",
        "title": "Use DNS Filtering Services",
        "health": "unhealthy",
        "controls": [{"key": "DNS-01", "health": "unhealthy", "passing": 1, "failing": 3}],
    },
    {"framework": "CIS_IG1", "key": "10.1", "title": "Deploy and Maintain Anti-Malware Software", "health": "healthy", "controls": []},
    {"framework": "NIST_CSF_2", "key": "GV.OC-01", "title": None, "health": "unhealthy", "controls": []},
    {"framework": "NIST_CSF_2", "key": "PR.AA-01", "title": None, "health": None, "controls": []},
]


def test_the_requirements_are_accepted_limited_to_the_two_frameworks_and_default_to_none():
    assert sf.ReportIn.model_validate(body()).report.requirements == []
    ok = sf.ReportIn.model_validate(body(requirements=REQUIREMENTS))
    assert len(ok.report.requirements) == 4
    for bad in (
        {**REQUIREMENTS[0], "framework": "SOC2"},
        {**REQUIREMENTS[0], "key": ""},
        {**REQUIREMENTS[0], "controls": [{"key": "x", "passing": -1, "failing": 0}]},
    ):
        with pytest.raises(ValidationError):
            sf.ReportIn.model_validate(body(requirements=[bad]))


def test_a_catalog_framework_gets_its_own_requirements_keyed_by_the_catalog_id_and_counted_by_health():
    report = sf.ReportIn.model_validate(body(requirements=REQUIREMENTS)).report
    cis = sf.mapping_for(report, "CIS-IG1", None)
    assert cis.mapped and set(cis.requirements) == {"9.2", "10.1"}
    assert cis.requirements["9.2"].health == "unhealthy" and cis.requirements["9.2"].controls[0].failing == 3
    assert cis.summary == {"unhealthy": 1, "healthy": 1}
    nist = sf.mapping_for(report, "NIST-CSF", None)
    assert set(nist.requirements) == {"GV.OC-01", "PR.AA-01"} and nist.summary == {"unhealthy": 1, "unknown": 1}


def test_a_framework_secureframe_is_not_mapped_to_here_or_no_report_yet_is_not_an_error():
    report = sf.ReportIn.model_validate(body(requirements=REQUIREMENTS)).report
    assert sf.mapping_for(report, "SOC2", None).mapped is False
    assert sf.mapping_for(None, "NIST-CSF", None).mapped is False
    assert sf.mapping_for(None, "NIST-CSF", None).requirements == {}


def test_the_cis_ig1_catalog_has_the_56_safeguards_in_their_controls_and_the_framework_is_known_to_the_api():
    from app.api.v1.endpoints.compliance import FRAMEWORKS
    from app.services.compliance_catalog import CATALOGS

    cis = CATALOGS["CIS-IG1"]
    assert len(cis) == 56 and len({c[1] for c in cis}) == 56
    assert {c[0].split(".")[0] for c in cis} == {
        str(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 17)
    }, "IG1 has no control 13, 16 or 18 safeguards"
    assert FRAMEWORKS["CIS-IG1"]["9.2"] == "Use DNS Filtering Services"
    assert set(sf.FRAMEWORK_KEYS) <= set(CATALOGS)
