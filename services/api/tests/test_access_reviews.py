"""Access reviews: who is on the list and what is flagged, then the whole review on a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import access_reviews as ep
from app.db.rls import set_rls_context
from app.services import access_reviews as rules
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def mfa(upn, **over):
    base = {
        "upn": upn,
        "display_name": None,
        "admin": False,
        "enabled": True,
        "user_type": "Member",
        "registered": True,
        "licensed": True,
        "days_since_signin": 3,
    }
    return SimpleNamespace(**{**base, **over})


def test_people_are_flagged_for_what_deserves_a_second_look_and_the_most_flagged_come_first():
    lines = rules.entries_from_mfa_users(
        [
            mfa("ok@acme.com"),
            mfa("boss@acme.com", admin=True, registered=False),
            mfa("old@acme.com", days_since_signin=200),
            mfa("gone@acme.com", enabled=False, registered=False),
            mfa("guest@partner.com", user_type="Guest"),
        ]
    )
    by = {ln["person"]: ln for ln in lines}
    assert by["ok@acme.com"]["flags"] == [] and by["ok@acme.com"]["access"] == "Microsoft 365, member, licensed"
    assert by["boss@acme.com"]["flags"] == ["administrator", "no multi-factor"] and "administrator" in by["boss@acme.com"]["access"]
    assert by["old@acme.com"]["flags"] == ["no sign-in for 200 days"]
    assert by["gone@acme.com"]["flags"] == ["disabled account"], "a disabled account is not also called 'no multi-factor'"
    assert by["guest@partner.com"]["flags"] == ["guest"]
    assert [ln["person"] for ln in lines][0] == "boss@acme.com" and lines[-1]["person"] == "ok@acme.com"


def test_another_tools_people_and_typed_names():
    rows = [
        SimpleNamespace(email="a@x.com", display_name="A", enabled=True, kind="user"),
        SimpleNamespace(email="shared@x.com", display_name=None, enabled=None, kind="shared"),
        SimpleNamespace(email="off@x.com", display_name=None, enabled=False, kind="user"),
    ]
    lines = rules.entries_from_identities(rows, "Dropsuite")
    assert [(ln["person"], ln["flags"]) for ln in lines] == [
        ("off@x.com", ["disabled account"]),
        ("shared@x.com", ["shared account"]),
        ("a@x.com", []),
    ]
    assert lines[2]["access"] == "Dropsuite: user"
    typed = rules.entries_from_names(["  Dana ", "dana", "", "Lee"], "Door badges")
    assert [t["person"] for t in typed] == ["Dana", "Lee"] and typed[0]["access"] == "Door badges"


def test_a_review_can_be_completed_only_when_everyone_is_decided_and_the_summary_says_what_was_decided():
    assert rules.can_complete(["keep", "remove"]) == (True, 0)
    assert rules.can_complete(["keep", "pending", "pending"]) == (False, 2)
    assert rules.can_complete([]) == (False, 0)
    assert rules.summarize(["keep", "keep", "remove"]) == "3 people reviewed: 2 keep their access, 1 to have it removed."


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
                text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ar-{n}", "s": f"ar-{n}-{tid.hex[:8]}"}
            )
        snap = uuid.uuid4()
        for upn, admin, reg in (("boss@acme.com", True, False), ("ok@acme.com", False, True), ("fine@acme.com", False, True)):
            await conn.execute(
                text(
                    "insert into identity_mfa_users (tenant_id, source, user_id, upn, enabled, admin, licensed, registered, capable, ca_enforced, security_defaults, snapshot_id) "
                    "values (:t, 'cipp', :u, :upn, true, :a, true, :r, :r, false, false, :s)"
                ),
                {"t": acme, "u": upn, "upn": upn, "a": admin, "r": reg, "s": snap},
            )
    yield SimpleNamespace(
        acme=acme, birch=birch, engine=engine, user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com")
    )
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (acme, birch):
            for table in ("access_review_entries", "access_reviews", "identity_mfa_users"):
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
async def test_a_review_snapshots_the_people_flags_the_admin_first_and_is_completed_only_when_all_are_decided(world):
    w = world
    listing = await run(w.acme, lambda db: ep.list_reviews(w.acme, db, w.user))
    assert [(s.system, s.people) for s in listing.systems] == [("Microsoft 365", 3)]
    review = await run(
        w.acme,
        lambda db: ep.start_review(
            ep.ReviewIn(
                name="Q4 access review", system="Microsoft 365", reviewer="Hal", due_date=datetime.now(UTC).date() + timedelta(days=30)
            ),
            w.acme,
            db,
            w.user,
        ),
    )
    assert review.people == 3 and review.pending == 3 and review.flagged == 1 and review.status == "open"
    assert review.entries[0].person == "boss@acme.com" and "administrator" in review.entries[0].flags
    with pytest.raises(HTTPException) as early:
        await run(w.acme, lambda db: ep.complete(review.id, w.acme, db, w.user))
    assert early.value.status_code == 409 and "3 people are still waiting" in early.value.detail
    bulk = await run(w.acme, lambda db: ep.decide_all(review.id, ep.BulkIn(decision="keep"), w.acme, db, w.user))
    assert (bulk.keep, bulk.pending) == (2, 1), "the flagged administrator is left for a look of its own"
    boss = next(e for e in bulk.entries if e.person == "boss@acme.com")
    done = await run(
        w.acme, lambda db: ep.decide(review.id, boss.id, ep.DecisionIn(decision="remove", note="left in March"), w.acme, db, w.user)
    )
    assert done.pending == 0 and done.remove == 1
    finished = await run(w.acme, lambda db: ep.complete(review.id, w.acme, db, w.user))
    assert (
        finished.status == "complete"
        and finished.summary == "3 people reviewed: 2 keep their access, 1 to have it removed."
        and finished.completed_by == "hal@goliveoak.com"
    )
    with pytest.raises(HTTPException) as again:
        await run(w.acme, lambda db: ep.decide(review.id, boss.id, ep.DecisionIn(decision="keep"), w.acme, db, w.user))
    assert again.value.status_code == 409
    with pytest.raises(HTTPException) as twice:
        await run(w.acme, lambda db: ep.complete(review.id, w.acme, db, w.user))
    assert twice.value.status_code == 409


@needs_pg
@pytest.mark.asyncio
async def test_typed_names_work_for_a_system_with_no_source_nothing_to_review_is_refused_and_another_client_sees_nothing(world):
    w = world
    typed = await run(
        w.acme,
        lambda db: ep.start_review(ep.ReviewIn(name="Door badges", system="Door badges", people=["Dana", "Lee"]), w.acme, db, w.user),
    )
    assert typed.people == 2 and typed.flagged == 0
    with pytest.raises(HTTPException) as nobody:
        await run(w.acme, lambda db: ep.start_review(ep.ReviewIn(name="Nothing here", system="Unknown tool"), w.acme, db, w.user))
    assert nobody.value.status_code == 422
    other = await run(w.birch, lambda db: ep.list_reviews(w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None)))
    assert other.reviews == [] and other.systems == []
    with pytest.raises(HTTPException) as foreign:
        await run(w.birch, lambda db: ep.get_review(typed.id, w.birch, db, w.user))
    assert foreign.value.status_code == 404
    decision = typed.entries[0]
    with pytest.raises(HTTPException) as wrong_review:
        await run(w.acme, lambda db: ep.decide(uuid.uuid4(), decision.id, ep.DecisionIn(decision="keep"), w.acme, db, w.user))
    assert wrong_review.value.status_code == 404
    listed = await run(w.acme, lambda db: ep.list_reviews(w.acme, db, w.user))
    assert [r.name for r in listed.reviews] == ["Door badges"]
    overdue = await run(
        w.acme,
        lambda db: ep.start_review(
            ep.ReviewIn(name="Late one", system="Door badges", people=["Sam"], due_date=datetime.now(UTC).date() - timedelta(days=2)),
            w.acme,
            db,
            w.user,
        ),
    )
    assert overdue.overdue is True
