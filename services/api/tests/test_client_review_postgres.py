"""The client review endpoint against a REAL Postgres (opt in with AISOC_TEST_PG_URL, a DISPOSABLE, fully migrated database incl. migration 094)."""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from app.api.v1.endpoints import client_review as ep
from app.db.rls import set_rls_context
from app.db.rls_scope import acting_as_tenant
from app.models.signin import IdentityMfaUser, IdentitySecureScore
from app.services.device_upsert import DeviceReport, upsert_device
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:8]
    ids = {k: uuid.uuid4() for k in ("msp", "client", "stranger")}
    engine = create_async_engine(PG_URL)
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        for key, tid in ids.items():
            await c.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                {
                    "i": tid,
                    "n": f"cr-{key}-{tag}",
                    "s": f"cr-{key}-{tag}",
                    "p": ids["msp"] if key == "client" else None,
                    "r": "child" if key == "client" else "parent",
                },
            )
        for sev, status, days_ago in (
            ("critical", "new", 1),
            ("high", "investigating", 3),
            ("low", "resolved", 2),
            ("critical", "new", 60),
        ):
            await c.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, created_at, updated_at) "
                    "values (gen_random_uuid(), :t, 'x', :sev, :st, now() - make_interval(days => :d), now() - make_interval(days => :d))"
                ),
                {"t": ids["client"], "sev": sev, "st": status, "d": days_ago},
            )
        for n, (status, days_ago) in enumerate((("new", 2), ("closed", 5), ("resolved", 90))):
            await c.execute(
                text(
                    "insert into cases (id, tenant_id, case_number, title, status, created_at, updated_at) "
                    "values (gen_random_uuid(), :t, :n, 'c', :s, now() - make_interval(days => :d), now() - make_interval(days => :d))"
                ),
                {"t": ids["client"], "n": f"CR-{tag}-{n}", "s": status, "d": days_ago},
            )
    yield ids
    async with engine.begin() as c:
        await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        await c.execute(text("delete from cases where tenant_id = :t"), {"t": ids["client"]})
        await c.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
    await engine.dispose()


async def run(owner, work):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, owner)
            out = await work(db)
            await db.commit()
            return out
    finally:
        await engine.dispose()


async def test_the_review_counts_the_last_thirty_days_and_answers_the_checklist_from_what_is_held(world):
    async def seed(db):
        async with acting_as_tenant(db, world["client"]):
            for vendor, ext, host, os_name, kw in (
                ("huntress", "h1", "PC-1", "Microsoft Windows 11 Pro", {"serial": "CNB1234567"}),
                ("ninjaone", "n1", "PC-1", "Microsoft Windows 11 Pro", {"serial": "CNB1234567"}),
                ("ninjaone", "n2", "PC-2", "Microsoft Windows 10 Pro", {}),
            ):
                await upsert_device(db, world["client"], DeviceReport(vendor, ext, host, os=os_name, **kw))
            snap = uuid.uuid4()
            for uid, registered, admin in (("1", True, False), ("2", False, True)):
                db.add(
                    IdentityMfaUser(
                        tenant_id=world["client"],
                        source="cipp",
                        user_id=uid,
                        upn=f"{uid}@x.com",
                        enabled=True,
                        user_type="Member",
                        admin=admin,
                        licensed=True,
                        registered=registered,
                        ca_enforced=True,
                        snapshot_id=snap,
                    )
                )
            db.add(
                IdentitySecureScore(
                    tenant_id=world["client"],
                    source="cipp",
                    taken_at=datetime(2026, 10, 21, tzinfo=UTC),
                    current_score=130,
                    max_score=260,
                    average_score=54,
                    history=[],
                    improvements=[],
                )
            )
            await db.flush()

    await run(world["msp"], seed)
    r = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    assert r.client_name.startswith("cr-client-")
    assert (r.alerts.open, r.alerts.critical_open, r.alerts.high_open) == (3, 2, 1)
    assert (r.alerts.opened_30d, r.alerts.closed_30d) == (
        3,
        1,
    ), "the 60-day-old alert is outside the window; one alert was closed inside it"
    assert (r.cases.open, r.cases.opened_30d, r.cases.resolved_30d) == (1, 2, 1), "the 90-day-old resolved case is outside the window"
    assert r.devices.endpoints == 2
    cov = {c.tool: (c.have, c.of) for c in r.devices.coverage}
    assert cov["huntress"] == (1, 2) and cov["ninjaone"] == (2, 2)
    assert r.mfa is not None and (r.mfa["people"], r.mfa["with_mfa"], r.mfa["admins_without_mfa"]) == (2, 1, 1)
    assert r.secure_score is not None and (r.secure_score.percent, r.secure_score.average) == (50.0, 54.0)
    status = {i.key: i.status for i in r.readiness.items}
    assert status["mfa_admins"] == "not_met" and status["edr"] == "not_met" and status["management"] == "met"
    assert status["secure_score"] == "partly"
    assert status["backups"] == "unknown"


async def test_a_client_with_nothing_reports_unknown_not_failures_and_a_stranger_is_not_found(world):
    r = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    assert r.mfa is None and r.secure_score is None and r.devices.endpoints == 0
    assert {i.key: i.status for i in r.readiness.items}["edr"] == "unknown"
    with pytest.raises(HTTPException) as err:
        await run(world["msp"], lambda db: ep.client_review(world["stranger"], NS(tenant_id=world["msp"]), db))
    assert err.value.status_code == 404


def vcio_report(client="vcio-1", **over):
    base = {
        "vendor": "vciotoolbox",
        "vendor_client_id": client,
        "recommendations": {
            "total": 50,
            "pending": 40,
            "adopted": 8,
            "declined": 2,
            "top": [
                {"name": "Restrict Group Creation", "priority": "High", "adoption": "Pending", "due": "2026-06-12", "on_roadmap": False}
            ],
        },
        "risks": [
            {
                "name": "Cyber Liability",
                "category": "Financial Risk",
                "priority": "Medium",
                "impact": 4,
                "likelihood": 2,
                "score": 8,
                "inherent": "Medium",
            }
        ],
    }
    base.update(over)
    return ep.VcioReviewReport(**base)


async def test_a_mapped_clients_vcio_summary_is_stored_replaced_and_shown_in_the_review_and_an_unmapped_one_waits(world):
    async def alias(db):
        await db.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:t, 'vciotoolbox', 'vcio-1', 'vcio-1', 'vcio-1', :c, false, 'manual')"
            ),
            {"t": world["msp"], "c": world["client"]},
        )

    await run(world["msp"], alias)
    waiting = await run(world["msp"], lambda db: ep.apply_vcio_review(db, world["msp"], vcio_report(client="nobody")))
    assert (waiting.accepted, waiting.unmapped) == (0, 1)
    first = await run(world["msp"], lambda db: ep.apply_vcio_review(db, world["msp"], vcio_report()))
    assert (first.accepted, first.unmapped) == (1, 0)
    await run(
        world["msp"],
        lambda db: ep.apply_vcio_review(
            db, world["msp"], vcio_report(recommendations={"total": 51, "pending": 41, "adopted": 8, "declined": 2, "top": []})
        ),
    )
    r = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    assert r.vcio is not None
    assert (r.vcio.recommendations.total, r.vcio.recommendations.pending, r.vcio.recommendations.top) == (
        51,
        41,
        [],
    ), "the second report replaced the first"
    assert [(k.name, k.score) for k in r.vcio.risks] == [("Cyber Liability", 8.0)]


async def test_a_client_with_no_vcio_summary_has_none(world):
    r = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    assert r.vcio is None


def m365_report(client="m365-1", checks=None):
    return ep.M365ChecksReport(
        vendor="cipp",
        vendor_client_id=client,
        checks=checks
        if checks is not None
        else [
            {"key": "safe_attachments", "status": "met", "evidence": "2 Safe Attachments policies enabled."},
            {"key": "ga_count", "status": "not_met", "evidence": "1 Global Administrator"},
        ],
    )


async def test_a_mapped_clients_m365_checks_are_stored_replaced_and_answer_the_template_questions_and_an_unmapped_one_waits(world):
    async def alias(db):
        await db.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:t, 'cipp', 'm365-1', 'm365-1', 'm365-1', :c, false, 'manual')"
            ),
            {"t": world["msp"], "c": world["client"]},
        )

    await run(world["msp"], alias)
    waiting = await run(world["msp"], lambda db: ep.apply_m365_checks(db, world["msp"], m365_report(client="nobody")))
    assert (waiting.accepted, waiting.unmapped) == (0, 1)
    assert (await run(world["msp"], lambda db: ep.apply_m365_checks(db, world["msp"], m365_report()))).accepted == 1
    await run(
        world["msp"],
        lambda db: ep.apply_m365_checks(
            db, world["msp"], m365_report(checks=[{"key": "safe_attachments", "status": "not_met", "evidence": "none"}])
        ),
    )
    r = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    by_q = {a.question: a for a in r.m365}
    assert by_q["Ensure Safe Attachments policy is enabled"].status == "not_met", "the second report replaced the first"
    assert (
        by_q["Ensure that between two and four global admins are designated"].status == "needs_person"
    ), "a check the second report no longer has is not kept"
    assert r.m365_refreshed_at is not None


async def test_a_client_with_no_m365_checks_has_every_question_marked_needs_a_person(world):
    r = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    assert len(r.m365) == 99 and all(a.status == "needs_person" for a in r.m365) and r.m365_refreshed_at is None


async def test_a_review_of_the_owners_own_tenant_works_and_a_client_with_no_extra_data_gets_clean_defaults(world):
    own = await run(world["msp"], lambda db: ep.client_review(world["msp"], NS(tenant_id=world["msp"]), db))
    assert own.client_id == world["msp"] and len(own.tech_stack) == 24 and len(own.m365) == 99
    child = await run(world["msp"], lambda db: ep.client_review(world["client"], NS(tenant_id=world["msp"]), db))
    assert child.vcio is None and child.mfa is None and child.secure_score is None and child.m365_refreshed_at is None
    assert all(a.status == "needs_person" for a in child.m365)
    assert all(a.status in {"unknown", "seen", "not_seen"} for a in child.tech_stack)


async def test_history_records_only_changes_acceptances_expire_and_sweep_runs_are_kept_once_per_source(world):
    from app.api.v1.endpoints import client_posture as cp

    async def alias(db):
        await db.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:t, 'cipp', 'h-1', 'h-1', 'h-1', :c, false, 'manual')"
            ),
            {"t": world["msp"], "c": world["client"]},
        )

    await run(world["msp"], alias)
    first = [{"key": "a", "status": "met", "evidence": "one"}, {"key": "b", "status": "not_met", "evidence": "two"}]
    second = [{"key": "a", "status": "met", "evidence": "same status, new words"}, {"key": "b", "status": "partly", "evidence": "better"}]
    for checks in (first, first, second):
        await run(world["msp"], lambda db, checks=checks: ep.apply_m365_checks(db, world["msp"], m365_report(client="h-1", checks=checks)))
    hist = await run(world["msp"], lambda db: cp.check_history(world["client"], NS(tenant_id=world["msp"]), db))
    got = [(r.key, r.previous_status, r.status) for r in hist.rows]
    assert len(got) == 3 and set(got) == {("a", None, "met"), ("b", None, "not_met"), ("b", "not_met", "partly")}, "a repeat and a same-status refresh add nothing"
    only_b = await run(world["msp"], lambda db: cp.check_history(world["client"], NS(tenant_id=world["msp"]), db, key="b"))
    assert [r.status for r in only_b.rows] == ["partly", "not_met"], "newest first"

    user = NS(tenant_id=world["msp"], user_id=uuid.uuid4())
    out = await run(world["msp"], lambda db: cp.accept_check(world["client"], "b", cp.AcceptIn(reason="  Replace in January ", expires_in_days=30), user, db))
    assert out.reason == "Replace in January" and out.expires_at is not None
    again = await run(world["msp"], lambda db: cp.accept_check(world["client"], "b", cp.AcceptIn(reason="Still waiting"), user, db))
    assert again.expires_at is None, "a second acceptance replaces the first"
    with pytest.raises(HTTPException) as e:
        await run(world["msp"], lambda db: cp.accept_check(world["stranger"], "b", cp.AcceptIn(reason="not mine"), user, db))
    assert e.value.status_code == 404
    await run(world["msp"], lambda db: cp.remove_acceptance(world["client"], "b", user, db))
    left = (await run(world["msp"], lambda db: db.execute(text("select count(*) from client_check_acceptances where tenant_id = :t"), {"t": world["client"]}))).scalar_one()
    assert left == 0

    report = ep.SweepRunsReport(runs=[ep.SweepRunIn(source="ninjaone", title="NinjaOne client checks", accounts=10, sent=7, failed=1, waiting=2, skipped=0, first_error="Acme: boom")])
    assert await run(world["msp"], lambda db: ep.apply_sweep_runs(db, world["msp"], report)) == 1
    report2 = ep.SweepRunsReport(runs=[ep.SweepRunIn(source="ninjaone", title="NinjaOne client checks", accounts=10, sent=10, failed=0, waiting=0, skipped=0)])
    await run(world["msp"], lambda db: ep.apply_sweep_runs(db, world["msp"], report2))
    runs = await run(world["msp"], lambda db: cp.sweep_runs(NS(tenant_id=world["msp"]), db))
    assert [(r.source, r.sent, r.failed, r.health) for r in runs] == [("ninjaone", 10, 0, "ok")], "the latest pass replaces the previous one"


async def test_the_fleet_views_rank_clients_list_a_board_and_show_the_days_changes(world):
    from app.api.v1.endpoints import client_posture as cp

    async def alias(db):
        await db.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:t, 'cipp', 'f-1', 'f-1', 'f-1', :c, false, 'manual')"
            ),
            {"t": world["msp"], "c": world["client"]},
        )

    await run(world["msp"], alias)
    checks = [
        {"key": "cipp_inactive_accounts", "status": "not_met", "evidence": "4 licensed accounts have not signed in", "items": ["a@x.com (200 days)", "b@x.com (300 days)"]},
        {"key": "cipp_subscriptions", "status": "met", "evidence": "3 subscriptions, none lapsed"},
        {"key": "cipp_unused_licences", "status": "partly", "evidence": "9 of 20 unused"},
    ]
    report = ep.M365ChecksReport(vendor="cipp", vendor_client_id="f-1", source="cipp-health", checks=checks)
    await run(world["msp"], lambda db: ep.apply_m365_checks(db, world["msp"], report))
    user = NS(tenant_id=world["msp"], user_id=uuid.uuid4())

    summary = await run(world["msp"], lambda db: cp.fleet_summary(user, db))
    mine = [c for c in summary.clients if c.client_id == world["client"]]
    assert len(mine) == 1 and (mine[0].score, mine[0].met, mine[0].partly, mine[0].not_met) == (50, 1, 1, 1)
    assert mine[0].stale_tools == []

    board = await run(world["msp"], lambda db: cp.fleet_board("licences", user, db))
    rows = [(r.key, r.status) for r in board.rows if r.client_id == world["client"]]
    assert rows == [("cipp_inactive_accounts", "not_met"), ("cipp_unused_licences", "partly")], "worst first, and the fine check is left out"
    first = [r for r in board.rows if r.client_id == world["client"]][0]
    assert first.items == ["a@x.com (200 days)", "b@x.com (300 days)"], "the list behind a check survives storing and reading (a field a copy leaves out is lost silently)"
    with_met = await run(world["msp"], lambda db: cp.fleet_board("backups", user, db, include_met=True))
    assert [r for r in with_met.rows if r.client_id == world["client"]] == [], "a board only holds its own checks"
    with pytest.raises(HTTPException) as e:
        await run(world["msp"], lambda db: cp.fleet_board("nope", user, db))
    assert e.value.status_code == 404

    await run(world["msp"], lambda db: cp.accept_check(world["client"], "cipp_inactive_accounts", cp.AcceptIn(reason="Staff on leave"), user, db))
    again = await run(world["msp"], lambda db: cp.fleet_summary(user, db))
    mine = [c for c in again.clients if c.client_id == world["client"]][0]
    assert (mine.not_met, mine.accepted, mine.score) == (0, 1, 75), "an accepted check leaves the score"

    changes = await run(world["msp"], lambda db: cp.fleet_changes(user, db, days=1))
    mine_changes = [(c.key, c.status) for c in changes if c.client_id == world["client"]]
    assert mine_changes[0] == ("cipp_inactive_accounts", "not_met"), "what got worse comes first"
    assert len(mine_changes) == 3


async def test_license_counts_are_stored_diffed_into_history_and_totalled_across_clients(world):
    from datetime import timedelta

    from app.api.v1.endpoints import billing as bl

    async def alias(db):
        await db.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:t, 'ninjaone', 'n-1', 'n-1', 'n-1', :c, false, 'manual')"
            ),
            {"t": world["msp"], "c": world["client"]},
        )

    await run(world["msp"], alias)

    def report(client="n-1", **counts):
        return bl.LicenseCountsReport(vendor="ninjaone", vendor_client_id=client, counts=[bl.LicenseCountIn(item=k.replace("_", " "), unit="device", count=v) for k, v in counts.items()])

    waiting = await run(world["msp"], lambda db: bl.apply_license_counts(db, world["msp"], report("nobody", Macs=1)))
    assert (waiting.accepted, waiting.unmapped) == (0, 1)
    long_ago = datetime.now(UTC) - timedelta(days=40)
    await run(world["msp"], lambda db: bl.apply_license_counts(db, world["msp"], report(Windows_workstations=10, Macs=4), now=long_ago))
    await run(world["msp"], lambda db: bl.apply_license_counts(db, world["msp"], report(Windows_workstations=10, Macs=4), now=long_ago + timedelta(days=1)))
    await run(world["msp"], lambda db: bl.apply_license_counts(db, world["msp"], report(Windows_workstations=13)))

    user = NS(tenant_id=world["msp"], user_id=uuid.uuid4())
    got = await run(world["msp"], lambda db: bl.client_counts(world["client"], user, db, days=30))
    by = {r.item: r for r in got.rows}
    assert set(by) == {"Windows workstations"}, "Macs is no longer reported, so it is gone"
    assert (by["Windows workstations"].count, by["Windows workstations"].change) == (13, 3), "10 forty days ago, 13 now"

    log = await run(world["msp"], lambda db: bl.changes_log(user, db, days=90))
    mine = [(c.item, c.previous_count, c.count) for c in log if c.client_id == world["client"]]
    assert sorted(mine, key=str) == sorted([("Windows workstations", None, 10), ("Macs", None, 4), ("Windows workstations", 10, 13), ("Macs", 4, 0)], key=str), "an unchanged day adds nothing; a removal is a change to 0"
    assert log[0].observed_at >= log[-1].observed_at, "newest first"

    fleet = await run(world["msp"], lambda db: bl.summary(user, db, days=30))
    row = [t for t in fleet.rows if t.source == "ninjaone" and t.item == "Windows workstations"][0]
    assert (row.total >= 13, row.clients >= 1) == (True, True)

    with pytest.raises(HTTPException) as e:
        await run(world["msp"], lambda db: bl.client_counts(world["stranger"], user, db))
    assert e.value.status_code == 404


async def test_billed_lines_are_checked_against_the_tool_counts_they_are_mapped_to(world):
    from app.api.v1.endpoints import billing as bl

    async def aliases(db):
        for vendor in ("halopsa", "ninjaone"):
            await db.execute(
                text(
                    "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                    "values (:t, :v, :id, :nm, :nm, :c, false, 'manual')"
                ),
                {"t": world["msp"], "v": vendor, "id": f"r-{vendor}", "nm": f"r-{vendor}", "c": world["client"]},
            )

    await run(world["msp"], aliases)
    billed = bl.LicenseCountsReport(vendor="halopsa", vendor_client_id="r-halopsa", counts=[bl.LicenseCountIn(item="NinjaOne RMM (Included)", unit="other", count=16), bl.LicenseCountIn(item="Liongard (Included)", unit="other", count=1)])
    counted = bl.LicenseCountsReport(vendor="ninjaone", vendor_client_id="r-ninjaone", counts=[bl.LicenseCountIn(item="Windows workstations", unit="device", count=14), bl.LicenseCountIn(item="Macs", unit="device", count=4)])
    for r in (billed, counted):
        await run(world["msp"], lambda db, r=r: bl.apply_license_counts(db, world["msp"], r))
    user = NS(tenant_id=world["msp"], user_id=uuid.uuid4())

    before = await run(world["msp"], lambda db: bl.billing_map(user, db))
    un = {u["invoice_item"]: u for u in before.unmapped}
    assert "NinjaOne RMM (Included)" in un and un["NinjaOne RMM (Included)"]["suggestion"][0] == {"source": "ninjaone", "item": "Windows workstations"}
    assert un["Liongard (Included)"]["suggestion"] == []
    assert any(c.source == "ninjaone" and c.item == "Macs" for c in before.counted_items)
    assert not any(c.source == "halopsa" for c in before.counted_items), "what is billed is not something to map to"

    nothing = await run(world["msp"], lambda db: bl.reconcile_billing(user, db))
    assert [r for r in nothing.rows if r.client_id == world["client"]] == [] and nothing.unmapped_lines >= 2

    saved = await run(world["msp"], lambda db: bl.save_map(bl.MapIn(invoice_item=" NinjaOne RMM (Included) ", counted=[bl.CountedRef(source="ninjaone", item="Windows workstations"), bl.CountedRef(source="ninjaone", item="Macs")]), user, db))
    assert saved.invoice_item == "NinjaOne RMM (Included)"
    after = await run(world["msp"], lambda db: bl.reconcile_billing(user, db))
    mine = [r for r in after.rows if r.client_id == world["client"]]
    assert [(r.invoice_item, r.billed, r.counted, r.difference) for r in mine] == [("NinjaOne RMM (Included)", 16, 18, 2)]
    assert [p["count"] for p in mine[0].parts] == [14, 4]

    again = await run(world["msp"], lambda db: bl.billing_map(user, db))
    assert [m.invoice_item for m in again.mapped] == ["NinjaOne RMM (Included)"] and "NinjaOne RMM (Included)" not in {u["invoice_item"] for u in again.unmapped}

    await run(world["msp"], lambda db: bl.delete_map("NinjaOne RMM (Included)", user, db))
    gone = await run(world["msp"], lambda db: bl.billing_map(user, db))
    assert gone.mapped == []
