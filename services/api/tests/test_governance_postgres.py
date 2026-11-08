"""The review calendar and policy library on a REAL Postgres: items are listed soonest first with their state, a review moves the date, versions are numbered and only added, another owner's items are invisible.
Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import governance as ep
from app.api.v1.endpoints.governance import ItemIn, ItemPatch, VersionIn
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")]
TODAY = datetime.now(UTC).date()


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(ep, "emit_audit", noop)  # the audit log is append-only; the shared helper is tested elsewhere


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"g-{t.hex[:10]}"})
        await s.commit()
        s.info.update(a=a, b=b)
        yield s
        await off(s)
        await s.execute(text("delete from governance_versions where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from governance_items where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def user(t):
    return SimpleNamespace(tenant_id=t, user_id=None)


async def test_items_are_listed_soonest_first_with_their_state_and_a_review_moves_the_date(world):
    s, a = world, world.info["a"]
    await off(s)
    late = await ep.create_item(ItemIn(kind="vendor", title="Vendor review: Pax8", interval_days=180, next_due=TODAY - timedelta(days=3)), None, user(a), s)
    await off(s)
    soon = await ep.create_item(ItemIn(kind="policy", title="Acceptable use", interval_days=365, next_due=TODAY + timedelta(days=5)), None, user(a), s)
    await off(s)
    default = await ep.create_item(ItemIn(kind="evidence", title="Cyber insurance renewal evidence", interval_days=90), None, user(a), s)
    assert default.next_due == TODAY + timedelta(days=90), "no date given: today plus the interval"
    await off(s)
    rows = await ep.list_items(user(a), s)
    assert [(r.title, r.state) for r in rows] == [("Vendor review: Pax8", "overdue"), ("Acceptable use", "due soon"), ("Cyber insurance renewal evidence", "ok")]
    await off(s)
    done = await ep.mark_reviewed(late.id, None, user(a), s)
    assert done.last_reviewed_at == TODAY and done.next_due == TODAY + timedelta(days=180) and done.state == "ok"
    await off(s)
    moved = await ep.update_item(soon.id, ItemPatch(owner="Hal", next_due=date(2030, 1, 1)), None, user(a), s)
    assert moved.owner == "Hal" and moved.next_due == date(2030, 1, 1)


async def test_policy_versions_are_numbered_only_added_and_only_for_policies(world):
    s, a = world, world.info["a"]
    await off(s)
    pol = await ep.create_item(ItemIn(kind="policy", title="Incident response", interval_days=365), None, user(a), s)
    await off(s)
    other = await ep.create_item(ItemIn(kind="vendor", title="A vendor", interval_days=365), None, user(a), s)
    await off(s)
    with pytest.raises(HTTPException) as err:
        await ep.add_version(other.id, VersionIn(body="text"), None, user(a), s)
    assert err.value.status_code == 422
    await off(s)
    v1 = await ep.add_version(pol.id, VersionIn(body="First text", change_note="initial"), None, user(a), s)
    await off(s)
    v2 = await ep.add_version(pol.id, VersionIn(body="Second text"), None, user(a), s)
    assert (v1.version, v2.version) == (1, 2)
    await off(s)
    got = await ep.list_versions(pol.id, user(a), s)
    assert [(v.version, v.body) for v in got] == [(2, "Second text"), (1, "First text")], "newest first, the old text untouched"
    await off(s)
    assert {r.title: r.versions for r in await ep.list_items(user(a), s)} == {"Incident response": 2, "A vendor": 0}


async def test_another_owners_items_are_invisible_and_archiving_hides_without_deleting(world):
    s, a, b = world, world.info["a"], world.info["b"]
    await off(s)
    mine = await ep.create_item(ItemIn(kind="other", title="Mine", interval_days=30), None, user(a), s)
    await off(s)
    assert [r.title for r in await ep.list_items(user(b), s)] == []
    await off(s)
    with pytest.raises(HTTPException) as err:
        await ep.mark_reviewed(mine.id, None, user(b), s)
    assert err.value.status_code == 404
    await off(s)
    await ep.archive_item(mine.id, None, user(a), s)
    await off(s)
    assert await ep.list_items(user(a), s) == []
    await off(s)
    kept = (await s.execute(text("select count(*) from governance_items where id = :i"), {"i": mine.id})).scalar_one()
    assert kept == 1
