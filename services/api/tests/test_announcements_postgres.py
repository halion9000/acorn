"""Announcements: the pure text and date rules, and on a REAL Postgres what is live, the cap, who sees whose, and removal. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import announcements as ep
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

TODAY = datetime.now(UTC).date()


def test_the_message_is_one_line_of_plain_text_cut_at_400_characters():
    assert ep.clean_message("  Maintenance\n\ttonight \x00 at 9  ") == "Maintenance tonight at 9"
    assert ep.clean_message("<b>bold</b>") == "<b>bold</b>", "kept as text; the page never shows it as markup"
    assert len(ep.clean_message("x" * 900)) == ep.MAX_LEN
    assert ep.clean_message(" \n\t ") == ""


def test_an_announcement_shows_through_its_end_day_and_always_without_one():
    assert ep.is_live(None, TODAY) and ep.is_live(TODAY, TODAY) and ep.is_live(TODAY + timedelta(days=1), TODAY)
    assert not ep.is_live(TODAY - timedelta(days=1), TODAY)


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"an-{t.hex[:10]}"})
        await s.commit()
        s.info.update(a=SimpleNamespace(tenant_id=a, user_id=None, email="hal@example.com"), b=SimpleNamespace(tenant_id=b, user_id=None, email="x@y"))
        yield s
        await off(s)
        await s.execute(text("delete from announcements where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_a_posted_announcement_is_listed_for_its_own_organization_only_until_its_end_day_and_can_be_removed(world):
    s = world
    await off(s)
    made = await ep.post_announcement(ep.AnnouncementIn(message="  Maintenance tonight  ", tone="warning", ends_on=TODAY), s.info["a"], s)
    assert (made.message, made.tone, made.created_by) == ("Maintenance tonight", "warning", "hal@example.com")
    await off(s)
    assert [x.message for x in await ep.list_announcements(s.info["a"], s)] == ["Maintenance tonight"]
    await off(s)
    assert await ep.list_announcements(s.info["b"], s) == [], "another organization sees nothing"
    # An announcement whose end day has passed is no longer listed.
    await off(s)
    await s.execute(text("update announcements set ends_on = :d where id = :i"), {"d": TODAY - timedelta(days=1), "i": made.id})
    await s.commit()
    await off(s)
    assert await ep.list_announcements(s.info["a"], s) == []
    await off(s)
    again = await ep.post_announcement(ep.AnnouncementIn(message="Welcome"), s.info["a"], s)
    await off(s)
    with pytest.raises(HTTPException) as other:
        await ep.remove_announcement(again.id, s.info["b"], s)
    assert other.value.status_code == 404, "another organization cannot remove it"
    await off(s)
    await ep.remove_announcement(again.id, s.info["a"], s)
    await off(s)
    assert await ep.list_announcements(s.info["a"], s) == []


@needs_pg
@pytest.mark.asyncio
async def test_an_empty_text_or_a_past_end_day_is_refused_and_no_more_than_five_show_at_once(world):
    s = world
    for bad in (ep.AnnouncementIn(message="   "), ep.AnnouncementIn(message="x", ends_on=TODAY - timedelta(days=1))):
        await off(s)
        with pytest.raises(HTTPException) as err:
            await ep.post_announcement(bad, s.info["a"], s)
        assert err.value.status_code == 422
    for i in range(ep.MAX_LIVE):
        await off(s)
        await ep.post_announcement(ep.AnnouncementIn(message=f"n{i}"), s.info["a"], s)
    await off(s)
    with pytest.raises(HTTPException) as full:
        await ep.post_announcement(ep.AnnouncementIn(message="one too many"), s.info["a"], s)
    assert full.value.status_code == 409
    await off(s)
    assert len(await ep.list_announcements(s.info["a"], s)) == ep.MAX_LIVE
