"""The Compliance dashboard and the framework switches, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance_dashboard as ep
from app.api.v1.endpoints import risk_register as rr
from app.api.v1.endpoints.compliance import FRAMEWORKS
from app.db.rls import set_rls_context
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
    ),
]


@pytest.fixture
async def world():
    acme, birch = uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name in ((acme, "Acme Dental"), (birch, "Birch Law")):
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": tid, "n": name, "s": f"rr-{tag}-{str(tid)[:6]}"}
            )
    w = SimpleNamespace(
        acme=acme,
        birch=birch,
        user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com"),
        request=SimpleNamespace(client=None, headers={}),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
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


async def evidence(w, tenant, control, status, days_ago, framework="SOC2"):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        when = datetime.now(UTC) - timedelta(days=days_ago)
        await conn.execute(
            text(
                "insert into aisoc_compliance_evidence (id, tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, status, created_at) "
                "values (:i, :t, :f, :c, 'policy', 'x', '{}'::jsonb, :w, :st, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant, "f": framework, "c": control, "st": status, "w": when},
        )
    await engine.dispose()


async def switch(w, frameworks, tenant=None):
    t = tenant or w.acme
    request = w.request
    return await run(t, lambda db: ep.set_enabled_frameworks(ep.EnabledIn(frameworks=frameworks), request, t, db, w.user))


async def dash(w, tenant=None):
    t = tenant or w.acme
    return await run(t, lambda db: ep.dashboard(t, db, w.user))


async def test_nothing_is_on_until_a_person_turns_frameworks_on_and_more_than_one_can_be_on(world):
    w = world
    got = await run(w.acme, lambda db: ep.enabled_frameworks(w.acme, db, w.user))
    assert got.enabled == [] and "SOC2" in got.available and "HIPAA" in got.available
    out = await switch(w, ["SOC2", "HIPAA", "CIS-IG1"])
    assert out.enabled == ["CIS-IG1", "HIPAA", "SOC2"]
    again = await run(w.acme, lambda db: ep.enabled_frameworks(w.acme, db, w.user))
    assert again.enabled == out.enabled


async def test_the_list_given_is_the_whole_set_so_a_framework_left_out_is_turned_off_and_an_empty_list_turns_all_off(world):
    w = world
    await switch(w, ["SOC2", "HIPAA"])
    assert (await switch(w, ["HIPAA"])).enabled == ["HIPAA"]
    assert (await switch(w, [])).enabled == []
    assert (await run(w.acme, lambda db: ep.enabled_frameworks(w.acme, db, w.user))).enabled == []


async def test_a_framework_that_does_not_exist_is_refused_and_one_client_never_sees_anothers_switches(world):
    w = world
    with pytest.raises(HTTPException) as e:
        await switch(w, ["SOC2", "NOPE"])
    assert e.value.status_code == 422
    await switch(w, ["SOC2"])
    assert (await run(w.birch, lambda db: ep.enabled_frameworks(w.birch, db, w.user))).enabled == []


async def test_the_dashboard_adds_up_control_health_over_the_frameworks_that_are_on_only(world):
    w = world
    await evidence(w, w.acme, "CC1.1", "accepted", 10)  # healthy
    await evidence(w, w.acme, "CC1.2", "accepted", 500)  # at risk: expired
    await evidence(w, w.acme, "CC1.3", "rejected", 5)  # unhealthy
    await evidence(w, w.acme, "A1.1", "pending", 2)  # at risk: only pending
    await evidence(w, w.acme, next(iter(FRAMEWORKS["HIPAA"])), "accepted", 3, framework="HIPAA")  # a framework that is off
    empty = await dash(w)
    assert empty.enabled == [] and empty.health is None and empty.by_framework == []
    await switch(w, ["SOC2"])
    d = await dash(w)
    assert d.health.healthy == 1 and d.health.unhealthy == 1 and d.health.at_risk == 2
    assert d.health.total == 61 and d.health.not_tested == 57 and d.health.percent_healthy == 2
    assert [f.framework for f in d.by_framework] == ["SOC2"]
    expired = [a for a in d.action_items if a.kind == "evidence_expired"]
    assert (
        len(expired) == 1
        and expired[0].event == "Evidence expired"
        and expired[0].link == "/compliance/soc2"
        and expired[0].name.startswith("SOC2 CC1.2")
    )
    await switch(w, ["SOC2", "HIPAA"])
    both = await dash(w)
    assert both.health.total == 61 + 63 and both.health.healthy == 2


async def test_the_dashboard_counts_risks_by_level_and_lists_open_risk_tasks_with_overdue_ones_named(world):
    w = world
    r = await run(
        w.acme,
        lambda db: rr.create_risk(rr.RiskIn(title="Phishing leads to takeover", likelihood=4, impact=4), w.request, w.acme, db, w.user),
    )
    await run(w.acme, lambda db: rr.create_risk(rr.RiskIn(title="Low one", likelihood=1, impact=2), w.request, w.acme, db, w.user))
    yesterday = date.today() - timedelta(days=1)
    await run(w.acme, lambda db: rr.add_task(r.id, rr.TaskIn(title="Turn on MFA", owner="Hal", due_date=yesterday), w.acme, db, w.user))
    d = await dash(w)
    assert d.risks.critical == 1 and d.risks.low == 1 and d.risks.total == 2
    tasks = [a for a in d.action_items if a.kind == "risk_task"]
    assert len(tasks) == 1 and tasks[0].event == "Task overdue" and tasks[0].name == "Risk R-1: Turn on MFA" and tasks[0].owner == "Hal"


async def test_vendors_are_counted_by_risk_level_and_a_review_that_is_overdue_or_due_soon_is_an_action_item(world):
    from app.api.v1.endpoints import vendor_management as vm

    w = world
    user = w.user

    async def add(name, level, months=None):
        body = vm.VendorIn(name=name, risk_level=level, review_interval_months=months)
        return await run(w.acme, lambda db: vm.create_vendor(body, w.request, w.acme, db, user))

    await add("Microsoft", "high", 12)  # never reviewed and scheduled: due from the day it was added
    await add("Zoom", "low")  # no schedule: nothing to do
    await add("Legacy Fax", "unassessed")
    out = await dash(w)
    assert (out.vendors.total, out.vendors.high, out.vendors.low, out.vendors.unassessed) == (3, 1, 1, 1)
    items = [i for i in out.action_items if i.kind == "vendor_review"]
    assert [(i.name, i.event, i.link) for i in items] == [("Vendor Microsoft: security review", "Review due soon", "/compliance/vendors")]
    other = await dash(w, w.birch)
    assert other.vendors.total == 0 and not [i for i in other.action_items if i.kind == "vendor_review"], "another client sees none of it"


async def test_an_open_access_review_with_a_due_date_is_an_action_item_and_a_completed_one_is_not(world):
    from app.api.v1.endpoints import access_reviews as ar

    w = world
    past = datetime.now(UTC).date() - timedelta(days=3)
    late = await run(
        w.acme,
        lambda db: ar.start_review(
            ar.ReviewIn(name="Door badges", system="Door badges", people=["Dana"], reviewer="Hal", due_date=past), w.acme, db, w.user
        ),
    )
    done = await run(
        w.acme,
        lambda db: ar.start_review(ar.ReviewIn(name="Old one", system="Door badges", people=["Lee"], due_date=past), w.acme, db, w.user),
    )
    await run(w.acme, lambda db: ar.decide_all(done.id, ar.BulkIn(decision="keep"), w.acme, db, w.user))
    await run(w.acme, lambda db: ar.complete(done.id, w.acme, db, w.user))
    items = [i for i in (await dash(w)).action_items if i.kind == "access_review"]
    assert [(i.name, i.event, i.owner, i.link) for i in items] == [
        ("Access review: Door badges", "Review overdue", "Hal", "/compliance/access-reviews")
    ]
    assert late.overdue


async def test_an_open_audit_request_with_a_due_date_is_an_action_item_until_it_is_answered(world):
    from app.api.v1.endpoints import audits as au

    w = world
    past = datetime.now(UTC).date() - timedelta(days=4)
    audit = await run(w.acme, lambda db: au.start_audit(au.AuditIn(name="SOC 2 2026", framework="SOC2"), w.acme, db, w.user))
    made = await run(
        w.acme, lambda db: au.add_request(audit.id, au.RequestIn(title="Org chart", owner="Dana", due_date=past), w.acme, db, w.user)
    )
    items = [i for i in (await dash(w)).action_items if i.kind == "audit_request"]
    assert [(i.name, i.event, i.owner, i.link) for i in items] == [
        ("Audit SOC 2 2026: Org chart", "Request overdue", "Dana", "/compliance/audits")
    ]
    await run(w.acme, lambda db: au.patch_request(audit.id, made.items[0].id, au.RequestPatch(status="provided"), w.acme, db, w.user))
    assert not [i for i in (await dash(w)).action_items if i.kind == "audit_request"]


async def test_a_vendor_contract_ending_within_sixty_days_or_already_ended_is_an_action_item_and_a_distant_one_is_not(world):
    from app.api.v1.endpoints import vendor_management as vm

    w = world
    today = datetime.now(UTC).date()

    async def add(name, end):
        return await run(w.acme, lambda db: vm.create_vendor(vm.VendorIn(name=name, contract_end=end), w.request, w.acme, db, w.user))

    await add("Ends soon", today + timedelta(days=30))
    await add("Already ended", today - timedelta(days=5))
    await add("Far off", today + timedelta(days=200))
    await add("No contract date", None)
    items = [(i.name, i.event) for i in (await dash(w)).action_items if i.kind == "vendor_contract"]
    assert sorted(items) == [("Vendor Already ended: contract", "Contract ended"), ("Vendor Ends soon: contract", "Contract ends soon")]


async def test_an_accepted_risk_whose_acceptance_has_ended_or_ends_soon_is_an_action_item_and_a_distant_one_is_not(world):
    w = world
    mk = lambda title, days: run(  # noqa: E731
        w.acme,
        lambda db: rr.create_risk(
            rr.RiskIn(title=title, likelihood=2, impact=2, treatment="accept", accepted_until=date.today() + timedelta(days=days)), w.request, w.acme, db, w.user
        ),
    )
    await mk("Lapsed acceptance", -4)
    await mk("Soon acceptance", 12)
    await mk("Distant acceptance", 120)
    items = {i.name: i for i in (await dash(w)).action_items if i.kind == "risk_acceptance"}
    assert set(items) == {"Risk R-1: Lapsed acceptance", "Risk R-2: Soon acceptance"}
    assert items["Risk R-1: Lapsed acceptance"].event == "Acceptance ended"
    assert items["Risk R-2: Soon acceptance"].event == "Acceptance ends soon"
    assert items["Risk R-2: Soon acceptance"].link == "/compliance/risk-register"
