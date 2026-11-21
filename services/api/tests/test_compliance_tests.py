"""Automated control tests: the mapping is valid, a result follows the checks the client really has, and recording writes only its own evidence, on a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance_dashboard as dash
from app.api.v1.endpoints import compliance_tests as ep
from app.db.rls import set_rls_context
from app.services import compliance_tests as ct
from app.services.compliance_catalog import CATALOGS
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_every_control_a_test_answers_is_a_real_control_and_every_test_names_checks():
    ids = {fw: {cid for _g, cid, _t in rows} for fw, rows in CATALOGS.items()}
    for t in ct.TESTS:
        assert t.checks and t.controls and t.title and t.why, t.id
        assert len(set(t.checks)) == len(t.checks), t.id
        for fw, cid in t.controls:
            assert cid in ids[fw], f"{t.id}: {fw} has no control {cid}"
    assert len({t.id for t in ct.TESTS}) == len(ct.TESTS)


def test_a_result_follows_only_the_checks_the_client_has():
    t = ct.BY_ID["malware"]
    assert ct.evaluate(t, {})["state"] == ct.NOT_TESTED
    assert ct.evaluate(t, {"some_other_check": "not_met"})["state"] == ct.NOT_TESTED, "a check the test does not name proves nothing"
    assert ct.evaluate(t, {"huntress_protection": "met"}) == {
        "state": ct.PASS,
        "seen": {"huntress_protection": "met"},
        "met": 1,
        "total": 1,
    }
    assert ct.evaluate(t, {"huntress_protection": "met", "ninjaone_antivirus": "partly"})["state"] == ct.PARTLY
    failing = ct.evaluate(t, {"huntress_protection": "met", "ninjaone_antivirus": "partly", "liongard_edr_coverage": "not_met"})
    assert failing["state"] == ct.FAIL and failing["met"] == 1 and failing["total"] == 3, "one failure fails the test even when others pass"


def test_results_are_listed_failing_first_and_untested_last():
    results = ct.evaluate_all({"huntress_protection": "met", "cipp_ca_legacy_auth": "not_met", "ninjaone_patching": "partly"})
    states = [r["state"] for r in results]
    assert states[0] == ct.FAIL and states[1] == ct.PARTLY and states[2] == ct.PASS and states[-1] == ct.NOT_TESTED
    assert states == sorted(states, key=[ct.FAIL, ct.PARTLY, ct.PASS, ct.NOT_TESTED].index)


def test_evidence_is_written_only_for_tested_tests_and_frameworks_that_are_on():
    results = ct.evaluate_all({"huntress_protection": "met", "cipp_ca_legacy_auth": "not_met", "ninjaone_patching": "partly"})
    rows = ct.evidence_rows(results, {"SOC2", "CIS-IG1"})
    by = {(r["framework"], r["control_id"]): r for r in rows}
    assert by[("SOC2", "CC6.8")]["status"] == "accepted" and by[("CIS-IG1", "10.1")]["status"] == "accepted"
    assert by[("SOC2", "CC6.1")]["status"] == "rejected" and "fails" in by[("SOC2", "CC6.1")]["summary"]
    assert by[("SOC2", "CC7.1")]["status"] == "pending" and "partly met" in by[("SOC2", "CC7.1")]["summary"]
    assert not any(fw in ("NIST-CSF", "HIPAA", "ISO27001") for fw, _ in by), "frameworks that are off get nothing"
    assert not any(r["payload"]["test"] == "backups" for r in rows), "no backup checks: nothing written, not a failure"
    assert all(r["payload"]["source"] == "checks" for r in rows)


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    acme, birch = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, n in ((acme, "acme"), (birch, "birch")):
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ctt-{n}", "s": f"ctt-{n}-{tid.hex[:8]}"}
            )
        await conn.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2')"), {"t": acme})
        for source, checks in (
            ("huntress", '[{"key": "huntress_protection", "status": "met", "evidence": "all protected"}]'),
            (
                "cipp",
                '[{"key": "cipp_ca_legacy_auth", "status": "not_met", "evidence": "legacy sign-in allowed"}, {"key": "bogus", "status": "weird"}]',
            ),
        ):
            await conn.execute(
                text("insert into client_m365_checks (tenant_id, source, checks) values (:t, :s, CAST(:c AS JSONB))"),
                {"t": acme, "s": source, "c": checks},
            )
        await conn.execute(
            text(
                "insert into aisoc_compliance_evidence (id, tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, status, created_at) "
                "values (:i, :t, 'SOC2', 'CC6.1', 'policy', 'a person accepted this', '{}'::jsonb, now(), 'accepted', now())"
            ),
            {"i": uuid.uuid4(), "t": acme},
        )
    yield SimpleNamespace(acme=acme, birch=birch, engine=engine, user=SimpleNamespace(tenant_id=acme, user_id=None))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (acme, birch):
            for table in ("aisoc_compliance_evidence", "client_m365_checks", "compliance_enabled_frameworks"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": t})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [acme, birch]})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_results_come_from_the_checks_read_live_and_reading_writes_nothing(world):
    w = world
    out = await run(w.acme, lambda db: ep.list_tests(w.acme, db, w.user))
    by = {r.id: r for r in out.results}
    assert by["malware"].state == "pass" and by["legacy-auth"].state == "fail" and by["backups"].state == "not_tested"
    assert out.checks_held == 2, "the check with a made-up status is ignored"
    assert out.counts["fail"] == 1 and out.counts["pass"] == 1 and out.enabled == ["SOC2"]
    assert {(c.framework, c.on) for c in by["malware"].controls} >= {("SOC2", True), ("HIPAA", False)}
    async with w.engine.begin() as conn:
        assert (
            await conn.execute(
                text("select count(*) from aisoc_compliance_evidence where tenant_id = :t and raw_payload ->> 'source' = 'checks'"),
                {"t": w.acme},
            )
        ).scalar_one() == 0


@needs_pg
@pytest.mark.asyncio
async def test_recording_writes_evidence_for_the_frameworks_that_are_on_replaces_only_its_own_and_moves_the_overview(world):
    w = world
    first = await run(w.acme, lambda db: ep.record_tests(w.acme, db, w.user))
    assert (
        first.written == 2 and first.replaced == 0
    ), "CC6.8 from the malware test and CC6.1 from the legacy sign-in test: SOC2 is the only framework on"
    again = await run(w.acme, lambda db: ep.record_tests(w.acme, db, w.user))
    assert again.written == first.written and again.replaced == first.written, "recording twice replaces, never piles up"
    async with w.engine.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "select control_id, status, raw_payload ->> 'source' as src from aisoc_compliance_evidence where tenant_id = :t order by control_id, status"
                ),
                {"t": w.acme},
            )
        ).all()
    assert [(r.control_id, r.status, r.src) for r in rows] == [
        ("CC6.1", "accepted", None),
        ("CC6.1", "rejected", "checks"),
        ("CC6.8", "accepted", "checks"),
    ], "the person's own evidence is untouched"
    overview = await run(w.acme, lambda db: dash.dashboard(w.acme, db, w.user))
    assert (
        overview.health is not None and overview.health.unhealthy == 1
    ), "CC6.1 is now unhealthy: the automated test failed it, whatever a person accepted"
    other = await run(w.birch, lambda db: ep.list_tests(w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None)))
    assert other.checks_held == 0 and other.counts["not_tested"] == len(ct.TESTS)
    assert datetime.now(UTC).year >= 2026


def test_a_test_turned_off_in_the_library_is_marked_and_writes_no_evidence_and_only_real_tests_count():
    first = ct.TESTS[0].id
    assert ct.disabled_of({"compliance_tests": {"disabled": [first, "no-such-test", 5]}}) == frozenset({first})
    assert ct.disabled_of(None) == frozenset() and ct.disabled_of({}) == frozenset()
    checks = {k: "met" for t in ct.TESTS for k in t.checks}
    results = ct.evaluate_all(checks, frozenset({first}))
    assert [r["enabled"] for r in results if r["test"].id == first] == [False] and all(r["enabled"] for r in results if r["test"].id != first)
    every = {f for t in ct.TESTS for f, _ in t.controls}
    rows = ct.evidence_rows(results, every)
    assert not any(r["payload"]["test"] == first for r in rows), "no evidence for the test that is off"
    assert any(r["payload"]["test"] != first for r in rows)
    assert all(r["enabled"] for r in ct.evaluate_all(checks)), "everything is on by default"


@needs_pg
@pytest.mark.asyncio
async def test_turning_a_test_off_removes_it_from_the_counts_and_from_what_is_recorded_and_unknown_names_are_refused(world):
    from fastapi import HTTPException

    w = world
    before = await run(w.acme, lambda db: ep.list_tests(w.acme, db, w.user))
    assert before.counts["fail"] == 1 and all(r.enabled for r in before.results)

    async def save(disabled):
        async def work(db):
            out = await ep.save_library(ep.LibraryIn(disabled=disabled), w.acme, db, w.user)
            return out

        return await run(w.acme, work)

    out = await save(["legacy-auth"])
    by = {r.id: r for r in out.results}
    assert by["legacy-auth"].enabled is False and by["malware"].enabled is True
    assert out.counts["fail"] == 0 and out.counts["pass"] == 1, "a test that is off is not counted"
    listed = await run(w.acme, lambda db: ep.list_tests(w.acme, db, w.user))
    assert {r.id: r.enabled for r in listed.results}["legacy-auth"] is False, "it is remembered"
    await run(w.acme, lambda db: ep.record_tests(w.acme, db, w.user))
    async with w.engine.begin() as conn:
        tests = (await conn.execute(text("select raw_payload ->> 'test' from aisoc_compliance_evidence where tenant_id = :t and raw_payload ->> 'source' = 'checks'"), {"t": w.acme})).scalars().all()
    assert "legacy-auth" not in tests and "malware" in tests
    with pytest.raises(HTTPException) as e:
        await save(["nope"])
    assert e.value.status_code == 422
    back = await save([])
    assert all(r.enabled for r in back.results) and back.counts["fail"] == 1
