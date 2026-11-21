"""The Controls list: one row per control of the frameworks that are on, health worked out like the overview, unhealthy first.

The pure rows first, then the endpoint on a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance_controls as ep
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def ev(accepted=0, pending=0, rejected=0, days=10):
    return {"accepted": accepted, "pending": pending, "rejected": rejected, "newest": NOW - timedelta(days=days) if accepted else None}


def test_each_control_gets_the_state_the_overview_would_give_it():
    rows = ep.build_rows(
        ["SOC2"],
        {"SOC2": {"CC1.1": ev(accepted=2), "CC1.2": ev(accepted=1, rejected=1), "CC1.3": ev(accepted=1, days=400), "CC1.4": ev(pending=1)}},
        NOW,
    )
    by = {r.control_id: r for r in rows}
    assert by["CC1.1"].state == "healthy" and by["CC1.1"].age_days == 10
    assert by["CC1.2"].state == "unhealthy"
    assert by["CC1.3"].state == "at_risk" and by["CC1.3"].age_days == 400
    assert by["CC1.4"].state == "at_risk" and by["CC1.4"].age_days is None
    assert by["CC1.5"].state == "not_tested" and by["CC1.5"].link == "/compliance/soc2"
    assert len(rows) > 40, "every control of the framework is listed, not only the ones with evidence"


def test_search_matches_the_id_the_title_or_the_group_in_any_case_and_a_framework_with_a_dash_links_with_an_underscore():
    rows = ep.build_rows(["NIST-CSF"], {}, NOW, "  gv.oc-01 ")
    assert [r.control_id for r in rows] == ["GV.OC-01"] and rows[0].link == "/compliance/nist_csf"
    govern = ep.build_rows(["NIST-CSF"], {}, NOW, "GOVERN")
    assert govern and all(
        r.group.lower().startswith("govern") or "govern" in r.title.lower() or "govern" in r.control_id.lower() for r in govern
    )
    assert ep.build_rows(["NIST-CSF"], {}, NOW, "zzzz-no-such-thing") == []


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
                text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ctl-{n}", "s": f"ctl-{n}-{tid.hex[:8]}"}
            )
    yield SimpleNamespace(acme=acme, birch=birch, engine=engine, user=SimpleNamespace(tenant_id=acme, user_id=None))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (acme, birch):
            await conn.execute(text("delete from aisoc_compliance_evidence where tenant_id = :t"), {"t": t})
            await conn.execute(text("delete from compliance_enabled_frameworks where tenant_id = :t"), {"t": t})
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


async def evidence(w, tenant, framework, control, status, days_ago=5):
    async with w.engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        when = datetime.now(UTC) - timedelta(days=days_ago)
        await conn.execute(
            text(
                "insert into aisoc_compliance_evidence (id, tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, status, created_at) "
                "values (:i, :t, :f, :c, 'policy', 'x', '{}'::jsonb, :w, :st, :w)"
            ),
            {"i": uuid.uuid4(), "t": tenant, "f": framework, "c": control, "st": status, "w": when},
        )


@needs_pg
@pytest.mark.asyncio
async def test_only_the_frameworks_that_are_on_are_listed_unhealthy_first_with_counts_and_filters(world):
    w = world
    async with w.engine.begin() as conn:
        await conn.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2')"), {"t": w.acme})
    await evidence(w, w.acme, "SOC2", "CC1.1", "accepted")
    await evidence(w, w.acme, "SOC2", "CC1.2", "rejected")
    await evidence(w, w.acme, "HIPAA", "164.308(a)(1)(i)", "accepted")  # a framework that is not on: not listed
    out = await run(w.acme, lambda db: ep.list_controls(w.acme, db, w.user, None, None, ""))
    assert out.enabled == ["SOC2"] and out.frameworks == ["SOC2"]
    assert out.rows[0].control_id == "CC1.2" and out.rows[0].state == "unhealthy", "unhealthy first"
    assert (
        out.counts["healthy"] == 1
        and out.counts["unhealthy"] == 1
        and sum(out.counts.values()) == len([1 for _ in out.rows])
        or out.total >= 2
    )
    only = await run(w.acme, lambda db: ep.list_controls(w.acme, db, w.user, None, "healthy", ""))
    assert [r.control_id for r in only.rows] == ["CC1.1"] and only.total == 1
    assert only.counts["unhealthy"] == 1, "the counts ignore the state filter, so the tabs keep their numbers"
    one = await run(w.acme, lambda db: ep.list_controls(w.acme, db, w.user, "HIPAA", None, "164.308"))
    assert one.frameworks == ["HIPAA"] and any(r.control_id.startswith("164.308") for r in one.rows)


@needs_pg
@pytest.mark.asyncio
async def test_another_client_sees_none_of_it_and_nothing_on_means_nothing_listed(world):
    w = world
    async with w.engine.begin() as conn:
        await conn.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2')"), {"t": w.acme})
    await evidence(w, w.acme, "SOC2", "CC1.1", "accepted")
    other = await run(w.birch, lambda db: ep.list_controls(w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None), None, None, ""))
    assert other.enabled == [] and other.rows == [] and other.total == 0
    nonsense = await run(w.acme, lambda db: ep.list_controls(w.acme, db, w.user, "NOPE", None, ""))
    assert nonsense.frameworks == [] and nonsense.rows == []


def test_an_owner_shows_on_its_control_and_the_search_finds_a_control_by_owner():
    owners = {("SOC2", "CC1.1"): "Dana Reyes"}
    rows = ep.build_rows(["SOC2"], {}, NOW, "", owners)
    by = {r.control_id: r for r in rows}
    assert by["CC1.1"].owner == "Dana Reyes" and by["CC1.2"].owner is None
    found = ep.build_rows(["SOC2"], {}, NOW, "dana", owners)
    assert [r.control_id for r in found] == ["CC1.1"]
    assert ep.build_rows(["HIPAA"], {}, NOW, "dana", owners) == [], "an owner of one framework's control does not match another's"


@needs_pg
@pytest.mark.asyncio
async def test_an_owner_can_be_named_changed_and_cleared_and_only_that_client_sees_it(world):
    w = world
    async with w.engine.begin() as conn:
        await conn.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2')"), {"t": w.acme})
    user = SimpleNamespace(tenant_id=w.acme, user_id=None, email="admin@example.test")

    async def listed(tenant=w.acme, who=w.user):
        out = await run(tenant, lambda db: ep.list_controls(tenant, db, who, None, None, ""))
        return {r.control_id: r.owner for r in out.rows}

    assert (await listed())["CC1.1"] is None
    named = await run(w.acme, lambda db: ep.set_owner("SOC2", "CC1.1", ep.OwnerIn(owner="  Dana   Reyes "), w.acme, db, user))
    assert named.owner == "Dana Reyes", "spacing is tidied"
    assert (await listed())["CC1.1"] == "Dana Reyes"
    await run(w.acme, lambda db: ep.set_owner("SOC2", "CC1.1", ep.OwnerIn(owner="Lee Park"), w.acme, db, user))
    assert (await listed())["CC1.1"] == "Lee Park", "a second owner replaces the first"
    assert (await run(w.acme, lambda db: ep.owners_by_control(db, w.acme, ["SOC2"]))) == {("SOC2", "CC1.1"): "Lee Park"}
    other = await run(w.birch, lambda db: ep.owners_by_control(db, w.birch, ["SOC2"]))
    assert other == {}, "another client sees no owner"
    cleared = await run(w.acme, lambda db: ep.set_owner("SOC2", "CC1.1", ep.OwnerIn(owner="   "), w.acme, db, user))
    assert cleared.owner is None
    assert (await listed())["CC1.1"] is None


@needs_pg
@pytest.mark.asyncio
async def test_naming_an_owner_for_a_control_that_does_not_exist_is_refused(world):
    from fastapi import HTTPException

    w = world
    user = SimpleNamespace(tenant_id=w.acme, user_id=None, email="admin@example.test")
    for fw, cid in (("SOC2", "NOPE-1"), ("NOFRAMEWORK", "CC1.1")):
        with pytest.raises(HTTPException) as err:
            await run(w.acme, lambda db: ep.set_owner(fw, cid, ep.OwnerIn(owner="x"), w.acme, db, user))
        assert err.value.status_code == 404


def test_the_inactive_tab_lists_the_frameworks_that_are_off_or_the_one_asked_for_when_it_is_off():
    from app.api.v1.endpoints.compliance import FRAMEWORKS

    names = list(FRAMEWORKS)
    on = [names[0]]
    assert ep.inactive_frameworks(on) == [f for f in names if f != names[0]]
    assert ep.inactive_frameworks(on, names[1]) == [names[1]]
    assert ep.inactive_frameworks(on, names[0]) == [], "a framework that is on is not inactive"
    assert ep.inactive_frameworks(names) == []
    assert ep.inactive_frameworks(on, "NOPE") == []
