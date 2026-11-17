"""The risk register, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

Risks are numbered per organization, one client never sees another's, a risk is archived and restored rather than deleted, tasks and every change are kept with the risk.
"""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import risk_register as ep
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


def risk(**over):
    base = {"title": "Phishing leads to a taken-over account", "likelihood": 4, "impact": 4, "category": "Email and phishing"}
    return ep.RiskIn(**{**base, **over})


async def add(w, tenant=None, **over):
    t = tenant or w.acme
    return await run(t, lambda db: ep.create_risk(risk(**over), w.request, t, db, w.user))


async def listing(w, tenant=None, archived=False):
    t = tenant or w.acme
    return await run(t, lambda db: ep.list_risks(t, db, w.user, archived))


async def test_risks_are_numbered_per_organization_and_scored_by_likelihood_times_impact(world):
    w = world
    a = await add(w)
    b = await add(w, title="Backups cannot be restored", likelihood=3, impact=5)
    other = await add(w, tenant=w.birch, title="Another client's own first risk")
    assert (a.ref, b.ref, other.ref) == ("R-1", "R-2", "R-1")
    assert (a.inherent_score, a.inherent_level) == (16, "critical")
    assert (b.inherent_score, b.inherent_level) == (15, "high")
    assert a.status == "open" and a.residual_score is None


async def test_one_client_never_sees_another_clients_risks(world):
    w = world
    await add(w, title="Acme only risk")
    await add(w, tenant=w.birch, title="Birch only risk")
    assert [r.title for r in (await listing(w)).risks] == ["Acme only risk"]
    assert [r.title for r in (await listing(w, w.birch)).risks] == ["Birch only risk"]
    mine = (await listing(w)).risks[0]
    with pytest.raises(HTTPException) as e:
        await run(w.birch, lambda db: ep.get_risk(mine.id, w.birch, db, w.user))
    assert e.value.status_code == 404


async def test_changes_are_kept_in_the_history_and_a_residual_rating_marks_the_risk_assessed(world):
    w = world
    r = await add(w)
    changed = await run(
        w.acme,
        lambda db: ep.update_risk(
            r.id,
            ep.RiskPatch(treatment="mitigate", residual_likelihood=2, residual_impact=3, owner="Hal", likelihood=5),
            w.request,
            w.acme,
            db,
            w.user,
        ),
    )
    assert changed.status == "assessed" and changed.residual_score == 6 and changed.residual_level == "medium"
    assert changed.inherent_score == 20
    details = [h.detail for h in changed.history if h.action == "changed"]
    assert (
        details
        and "Likelihood 4 to 5" in details[0]
        and "Treatment undecided to mitigate" in details[0]
        and "Owner none to Hal" in details[0]
    )
    cleared = await run(w.acme, lambda db: ep.update_risk(r.id, ep.RiskPatch(clear_residual=True), w.request, w.acme, db, w.user))
    assert cleared.status == "open" and cleared.residual_score is None


async def test_only_one_of_the_two_residual_values_is_refused(world):
    w = world
    r = await add(w)
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.update_risk(r.id, ep.RiskPatch(residual_likelihood=2), w.request, w.acme, db, w.user))
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        await add(w, residual_likelihood=2)
    assert e2.value.status_code == 422


async def test_a_risk_is_archived_not_deleted_cannot_be_changed_while_archived_and_can_be_restored(world):
    w = world
    r = await add(w)
    archived = await run(w.acme, lambda db: ep.archive_risk(r.id, w.request, w.acme, db, w.user))
    assert archived.status == "archived" and archived.archived_at is not None
    assert (await listing(w)).risks == []
    assert [x.id for x in (await listing(w, archived=True)).risks] == [r.id]
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.update_risk(r.id, ep.RiskPatch(owner="x"), w.request, w.acme, db, w.user))
    assert e.value.status_code == 409
    back = await run(w.acme, lambda db: ep.restore_risk(r.id, w.request, w.acme, db, w.user))
    assert back.status == "open" and back.archived_at is None
    assert [h.action for h in back.history][:2] == ["restored", "archived"]


async def test_tasks_count_as_open_until_done_and_overdue_ones_are_flagged(world):
    w = world
    r = await add(w)
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    r = await run(
        w.acme,
        lambda db: ep.add_task(r.id, ep.TaskIn(title="Turn on MFA for everyone", owner="Hal", due_date=yesterday), w.acme, db, w.user),
    )
    r = await run(
        w.acme, lambda db: ep.add_task(r.id, ep.TaskIn(title="Train staff", due_date=date.today() + timedelta(days=30)), w.acme, db, w.user)
    )
    assert [t.overdue for t in r.tasks] == [True, False] and r.open_tasks == 2
    s = (await listing(w)).summary
    assert (s.open_tasks, s.overdue_tasks, s.untreated, s.total) == (2, 1, 1, 1)
    r = await run(w.acme, lambda db: ep.update_task(r.id, r.tasks[0].id, ep.TaskPatch(done=True), w.acme, db, w.user))
    assert r.open_tasks == 1 and r.tasks[0].done and r.tasks[0].done_at is not None and not r.tasks[0].overdue
    assert (await listing(w)).summary.overdue_tasks == 0
    r = await run(w.acme, lambda db: ep.delete_task(r.id, r.tasks[1].id, w.acme, db, w.user))
    assert len(r.tasks) == 1


async def test_a_library_risk_is_added_once_and_marked_as_added(world):
    w = world
    lib = await run(w.acme, lambda db: ep.library(w.acme, db, w.user))
    assert len(lib) >= 12 and not any(i.added for i in lib)
    made = await run(w.acme, lambda db: ep.from_library(ep.LibraryPick(library_id="ransomware"), w.request, w.acme, db, w.user))
    assert made.title.startswith("Ransomware") and made.inherent_score == 15
    assert any(i.added for i in await run(w.acme, lambda db: ep.library(w.acme, db, w.user)))
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.from_library(ep.LibraryPick(library_id="ransomware"), w.request, w.acme, db, w.user))
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e2:
        await run(w.acme, lambda db: ep.from_library(ep.LibraryPick(library_id="nope"), w.request, w.acme, db, w.user))
    assert e2.value.status_code == 404


async def test_the_dashboard_counts_levels_and_places_each_risk_on_the_grid(world):
    w = world
    await add(w, likelihood=5, impact=5)
    await add(w, title="Low one", likelihood=1, impact=2)
    s = (await listing(w)).summary
    assert s.by_level == {"critical": 1, "high": 0, "medium": 0, "low": 1}
    assert s.matrix[0][4] == 1 and s.matrix[4][1] == 1
    assert s.untreated == 2


async def test_an_accepted_risk_can_carry_an_end_date_that_is_flagged_when_near_or_past_and_goes_when_it_is_no_longer_accepted(world):
    from datetime import date, timedelta

    w = world
    soon = date.today() + timedelta(days=10)
    a = await add(w, title="Accepted, ends soon", treatment="accept", accepted_until=soon)
    await add(w, title="Accepted, long off", treatment="accept", accepted_until=date.today() + timedelta(days=200))
    b = await add(w, title="Accepted, lapsed", treatment="accept", accepted_until=date.today() - timedelta(days=3))
    await add(w, title="Accepted, no end", treatment="accept")
    out = await listing(w)
    states = {r.title: r.acceptance_state for r in out.risks}
    assert states == {"Accepted, ends soon": "expiring", "Accepted, long off": "current", "Accepted, lapsed": "expired", "Accepted, no end": "none"}
    assert (out.summary.acceptance_expiring, out.summary.acceptance_expired) == (1, 1)
    moved = await run(w.acme, lambda db: ep.update_risk(a.id, ep.RiskPatch(treatment="mitigate"), w.request, w.acme, db, w.user))
    assert moved.accepted_until is None and moved.acceptance_state == "none", "the end date goes with the acceptance"
    cleared = await run(w.acme, lambda db: ep.update_risk(b.id, ep.RiskPatch(clear_accepted_until=True), w.request, w.acme, db, w.user))
    assert cleared.accepted_until is None
    extended = await run(w.acme, lambda db: ep.update_risk(b.id, ep.RiskPatch(accepted_until=date.today() + timedelta(days=90)), w.request, w.acme, db, w.user))
    assert extended.acceptance_state == "current"
    line = [h.detail for h in extended.history if h.action == "changed"][0]
    assert line.startswith("Accepted until ")


async def test_an_end_date_without_the_accept_treatment_is_refused(world):
    from datetime import date, timedelta

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        risk(treatment="mitigate", accepted_until=date.today() + timedelta(days=10))
    with pytest.raises(ValidationError):
        risk(accepted_until=date.today() + timedelta(days=10))
