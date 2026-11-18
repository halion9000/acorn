"""People checklists on a REAL Postgres: a checklist starts from the built-in list and again adds only what is missing, a task is ticked off with who and when and can be put back, a task of your own cannot repeat,
a leaver stays listed with their offboarding, and another owner sees nothing. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database, migration 211 applied)."""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import personnel as ep
from app.api.v1.endpoints.personnel import AddIn, DoneIn, StartIn
from app.services import personnel_tasks as pt
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    async def noop(**_kw):
        return None

    async def roster(_db, _tenant):
        return {"ann@x.com": "Ann Lee", "bob@x.com": None}

    monkeypatch.setattr(ep, "emit_audit", noop)
    monkeypatch.setattr(ep, "_roster", roster)  # the people list itself is tested with the Identities page


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"pe-{t.hex[:10]}"})
        await s.commit()
        s.info.update(a=a, b=b)
        yield s
        await off(s)
        await s.execute(text("delete from personnel_tasks where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def user(email="hal@x.com"):
    return SimpleNamespace(tenant_id=None, user_id=None, email=email)


async def test_start_again_tick_off_and_put_back(world):
    s, a = world, world.info["a"]
    await off(s)
    first = await ep.start_checklist(a, "Ann@x.com", StartIn(kind="onboarding"), None, user(), s)
    assert len(first) == len(pt.TEMPLATES["onboarding"]) and {t.email for t in first} == {"ann@x.com"}
    await off(s)
    again = await ep.start_checklist(a, "ann@x.com", StartIn(kind="onboarding"), None, user(), s)
    assert len(again) == len(first), "starting again adds nothing that is already there"
    await off(s)
    task = first[0]
    done = await ep.mark_task(a, task.id, DoneIn(done=True), None, user("Hal@X.com"), s)
    assert done.done_by == "hal@x.com" and done.done_at is not None and done.done_at <= datetime.now(UTC)
    await off(s)
    people = {p.email: p for p in await ep.list_people(a, s)}
    assert (people["ann@x.com"].onboarding.done, people["ann@x.com"].onboarding.total) == (1, len(first)) and not people["ann@x.com"].offboarding.started
    await off(s)
    back = await ep.mark_task(a, task.id, DoneIn(done=False), None, user(), s)
    assert back.done_at is None and back.done_by is None


async def test_a_task_of_your_own_cannot_repeat_and_can_be_removed_and_a_leaver_stays_listed(world):
    s, a = world, world.info["a"]
    await off(s)
    mine = await ep.add_task(a, "carl@x.com", AddIn(kind="offboarding", title="  Return the   badge "), None, user(), s)
    assert mine.title == "Return the badge"
    await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.add_task(a, "carl@x.com", AddIn(kind="offboarding", title="Return the badge"), None, user(), s)
    assert e.value.status_code == 409
    await off(s)
    people = {p.email: p for p in await ep.list_people(a, s)}
    assert people["carl@x.com"].active is False and people["carl@x.com"].offboarding.total == 1, "no longer in the directory, still listed with the checklist"
    assert people["ann@x.com"].active is True and people["ann@x.com"].name == "Ann Lee"
    await off(s)
    await ep.remove_task(a, mine.id, None, user(), s)
    await off(s)
    assert await ep.person_tasks(a, "carl@x.com", s) == []
    for bad in ("nope", "a b@x.com"):
        await off(s)
        with pytest.raises(HTTPException) as e:
            await ep.person_tasks(a, bad, s)
        assert e.value.status_code == 422


async def test_another_owner_sees_and_changes_nothing(world):
    s, a, b = world, world.info["a"], world.info["b"]
    await off(s)
    made = await ep.start_checklist(a, "ann@x.com", StartIn(kind="offboarding"), None, user(), s)
    await off(s)
    assert await ep.person_tasks(b, "ann@x.com", s) == []
    for call in (ep.mark_task(b, made[0].id, DoneIn(done=True), None, user(), s), ep.remove_task(b, made[0].id, None, user(), s)):
        await off(s)
        with pytest.raises(HTTPException) as e:
            await call
        assert e.value.status_code == 404
