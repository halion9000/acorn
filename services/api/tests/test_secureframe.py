"""Secureframe's report in A.C.O.R.N: what the route accepts, the percentage it shows, and (on a REAL Postgres, AISOC_TEST_PG_URL) that a report replaces the one before it and one organization never reads another's."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime, timedelta
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
            await conn.execute(text("delete from alerts where tenant_id = any(:t)"), {"t": [mine, other]})
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


TODAY = date(2026, 10, 29)


def day(days_ago, passing, failing):
    return (TODAY - timedelta(days=days_ago), passing, failing)


def test_the_change_is_the_newest_pass_rate_minus_the_oldest_in_the_window_in_points():
    assert sf.change_over([day(29, 50, 50), day(10, 60, 40), day(0, 80, 20)], TODAY) == 30.0
    assert sf.change_over([day(20, 90, 10), day(0, 80, 20)], TODAY) == -10.0


def test_there_is_no_change_to_report_from_too_little_or_too_young_a_history():
    assert sf.change_over([], TODAY) is None
    assert sf.change_over([day(0, 8, 2)], TODAY) is None
    assert sf.change_over([day(3, 5, 5), day(0, 8, 2)], TODAY) is None, "three days is not a trend"
    assert sf.change_over([day(0, 0, 0), day(20, 0, 0)], TODAY) is None, "days with nothing evaluated are ignored"
    assert sf.change_over([day(40, 1, 9), day(0, 9, 1)], TODAY) is None, "a day outside the 30 day window is ignored"


@pg
@pytest.mark.asyncio
async def test_a_day_is_recorded_once_with_the_latest_counts_and_the_view_reports_the_change(monkeypatch):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:t, 'sf', :s)"), {"t": tid, "s": f"sf-{tid.hex[:10]}"})
        await conn.execute(
            text("insert into secureframe_history (tenant_id, day, passing, failing) values (:t, :d, 50, 50)"),
            {"t": tid, "d": datetime.now(UTC).date() - timedelta(days=20)},
        )
    try:
        async with AsyncSession(engine) as db:

            async def verify(_db, _token):
                return tid

            async def adopt(_db, _owner):
                return None

            monkeypatch.setattr(sf, "_verify_core_feed_token", verify)
            monkeypatch.setattr(sf, "adopt_tenant", adopt)
            first = body(tests={**COUNTS, "passing": 6, "failing": 4})
            await sf.report_core_feed_secureframe("t", sf.ReportIn.model_validate(first), db)
            second = body(tests={**COUNTS, "passing": 8, "failing": 2})
            await sf.report_core_feed_secureframe("t", sf.ReportIn.model_validate(second), db)
            rows = (
                await db.execute(text("select passing, failing from secureframe_history where tenant_id = :t order by day"), {"t": tid})
            ).all()
            assert [tuple(r) for r in rows] == [(50, 50), (8, 2)], "twice on one day is one row, with the latest counts"
            view = await sf.secureframe_view(SimpleNamespace(tenant_id=tid), db)
            assert view.change_30_days == 30.0
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from secureframe_history where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from alerts where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from secureframe_reports where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()


# ---- the controls and their tests -----------------------------------------------------------------------------------------------------------------------------

TESTS = [
    {
        "key": "t-fail",
        "title": "MFA is required for every account",
        "state": "fail",
        "type": "integration",
        "owner": "Dana",
        "failing_since": "2026-10-20T00:00:00Z",
        "message": "3 accounts have no MFA",
        "action": "Require MFA for the 3 accounts.",
    },
    {"key": "t-pass", "title": "Password policy is uploaded", "state": "pass", "type": "upload", "action": "Upload the policy."},
]
CONTROLS = [
    {
        "key": "DNS-01",
        "name": "DNS filtering is enforced",
        "description": "Devices resolve names through a filtering service.",
        "health": "unhealthy",
        "implementation": "implemented",
        "owner": "Dana",
        "passing": 1,
        "failing": 4,
        "at_risk": 1,
        "tests": TESTS,
    },
    {"key": "ORG-01", "name": "Mission is documented", "health": "unhealthy", "passing": 0, "failing": 1, "tests": [TESTS[0]]},
]


def test_the_controls_and_their_tests_are_accepted_and_a_malformed_one_is_refused():
    ok = sf.ReportIn.model_validate(body(requirements=REQUIREMENTS, controls=CONTROLS)).report
    assert [c.key for c in ok.controls] == ["DNS-01", "ORG-01"] and ok.controls[0].tests[0].action == "Require MFA for the 3 accounts."
    assert sf.ReportIn.model_validate(body()).report.controls == [], "a report from before CORE sent them still reads"
    for bad in (
        {**CONTROLS[0], "key": ""},
        {**CONTROLS[0], "tests": [{**TESTS[0], "state": "maybe"}]},
        {**CONTROLS[0], "tests": [{**TESTS[0], "title": ""}]},
        {**CONTROLS[0], "failing": -1},
        {**CONTROLS[0], "tests": [TESTS[0]] * (sf.MAX_TESTS_PER_CONTROL + 1)},
    ):
        with pytest.raises(ValidationError):
            sf.ReportIn.model_validate(body(controls=[bad]))


def test_each_requirement_shows_its_controls_in_full_with_their_tests_and_counts_a_failing_test_once():
    requirements = [
        {
            "framework": "NIST_CSF_2",
            "key": "GV.OC-01",
            "title": None,
            "description": "The organizational mission is understood.",
            "health": "unhealthy",
            "controls": [
                {"key": "DNS-01", "health": "unhealthy", "passing": 1, "failing": 3},
                {"key": "ORG-01", "health": "unhealthy", "passing": 0, "failing": 1},
                {"key": "OLD-9", "health": "healthy", "passing": 2, "failing": 0},
            ],
        },
    ]
    report = sf.ReportIn.model_validate(body(requirements=requirements, controls=CONTROLS)).report
    req = sf.mapping_for(report, "NIST-CSF", None).requirements["GV.OC-01"]
    assert req.description == "The organizational mission is understood."
    dns, org, old = req.controls
    assert (dns.name, dns.description, dns.implementation, dns.owner) == (
        "DNS filtering is enforced",
        "Devices resolve names through a filtering service.",
        "implemented",
        "Dana",
    )
    assert (dns.passing, dns.failing, dns.at_risk) == (
        1,
        4,
        1,
    ), "the control's own counts, which are newer than the copy under the requirement"
    assert [(t.key, t.state, t.message, t.action) for t in dns.tests] == [
        ("t-fail", "fail", "3 accounts have no MFA", "Require MFA for the 3 accounts."),
        ("t-pass", "pass", None, "Upload the policy."),
    ]
    assert [t.key for t in org.tests] == ["t-fail"]
    assert (old.key, old.name, old.tests, old.passing) == (
        "OLD-9",
        None,
        [],
        2,
    ), "a control with no detail sent keeps what the requirement said about it"
    assert req.failing_tests == 1, "the same failing test under two controls is one thing to fix"


def test_a_report_without_control_detail_maps_exactly_as_before():
    report = sf.ReportIn.model_validate(body(requirements=REQUIREMENTS)).report
    cis = sf.mapping_for(report, "CIS-IG1", None)
    first = cis.requirements["9.2"].controls[0]
    assert (first.failing, first.name, first.tests, cis.requirements["9.2"].failing_tests, cis.requirements["9.2"].description) == (
        3,
        None,
        [],
        0,
        None,
    )
