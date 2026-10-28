"""A client's documentation on a REAL Postgres, as the application's own (row-level-security) role: stored per client, found by full-text search, pinned to the client a question names, refreshed in place, and
dropped when a record has not been refreshed for two weeks. Another organization's documents are never found.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database) and AISOC_TEST_PG_APP_URL (the application role on it).
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints.client_documents import client_documents_summary, find
from app.services import client_docs as cd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


def doc(i, title, body, kind="document", folder=None):
    return SimpleNamespace(id=i, kind=kind, title=title, folder=folder, body=body, url=f"https://x.itglue.com/{i}", updated_at=None)


@pytest.fixture
async def world():
    parent, park, school, stranger_parent = (uuid.uuid4() for _ in range(4))
    tag = parent.hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app = create_async_engine(APP_URL, poolclass=NullPool)
    ids = (parent, park, school, stranger_parent)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid, name, p, role in (
                (parent, f"Parent {tag}", None, "parent"),
                (park, f"Airport Security Park {tag}", parent, "child"),
                (school, f"Hill Country School {tag}", parent, "child"),
                (stranger_parent, f"Stranger {tag}", None, "parent"),
            ):
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :n, :p, :r)"),
                    {"i": tid, "n": name, "p": p, "r": role},
                )
        yield app, owner, SimpleNamespace(tag=tag, parent=parent, park=park, school=school, stranger=stranger_parent)
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from client_documents where tenant_id = any(:ids)"), {"ids": list(ids)})
            await conn.execute(text("delete from tenants where id = any(:ids)"), {"ids": [park, school, parent, stranger_parent]})
        await owner.dispose()
        await app.dispose()


async def store(app, by_tenant, vendor="itglue", now=None):
    async with AsyncSession(app) as db:
        n = await cd.apply_documents(db, by_tenant, vendor, now)
        await db.commit()
    return n


async def ask(app, w, question, **kw):
    async with AsyncSession(app) as db:
        return await find(db, w.parent, question, **kw)


@pytest.mark.asyncio
async def test_a_question_finds_the_best_document_with_the_matching_passage_and_stemmed_words(world):
    app, _, w = world
    await store(
        app,
        {
            w.park: [
                doc(
                    "d1",
                    "New hire onboarding guide",
                    "Step 1: create the account in Entra.\nStep 2: assign the laptop and enroll it in Intune.",
                ),
                doc("d2", "Firewall runbook", "Reset the firewall by holding the button for ten seconds."),
            ]
        },
    )
    hits = await ask(app, w, "how do we onboard a new hire")
    assert [h.title for h in hits][:1] == ["New hire onboarding guide"], "onboard matches onboarding; the firewall runbook does not match"
    assert "create the account" in hits[0].snippet
    assert hits[0].client == f"Airport Security Park {w.tag}" and hits[0].url == "https://x.itglue.com/d1"


@pytest.mark.asyncio
async def test_a_question_that_names_a_client_looks_only_in_that_clients_documents(world):
    app, _, w = world
    await store(
        app,
        {
            w.park: [doc("p1", "VPN setup", "Install the vpn client and sign in with your company email.")],
            w.school: [doc("s1", "VPN setup", "Use the school vpn portal with your student id.")],
        },
    )
    both = await ask(app, w, "how does the vpn setup work")
    assert {h.client for h in both} == {f"Airport Security Park {w.tag}", f"Hill Country School {w.tag}"}
    pinned = await ask(app, w, f"how does the vpn setup work for Airport Security Park {w.tag}")
    assert {h.client for h in pinned} == {f"Airport Security Park {w.tag}"}
    one = await ask(app, w, "vpn setup", client_id=w.school)
    assert {h.client for h in one} == {f"Hill Country School {w.tag}"}


@pytest.mark.asyncio
async def test_sending_a_record_again_updates_it_in_place(world):
    app, owner, w = world
    await store(app, {w.park: [doc("d1", "Wifi", "The guest network is called Pelican.")]})
    await store(app, {w.park: [doc("d1", "Wifi", "The guest network is called Heron.")]})
    assert [h.snippet for h in await ask(app, w, "guest network name")] and "Heron" in (await ask(app, w, "guest network name"))[0].snippet
    assert await ask(app, w, "pelican") == [], "the old text is gone from the search"
    async with owner.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        n = (await conn.execute(text("select count(*) from client_documents where tenant_id = :t"), {"t": w.park})).scalar_one()
    assert n == 1


@pytest.mark.asyncio
async def test_a_record_not_refreshed_for_two_weeks_is_dropped_by_the_next_report_and_other_vendors_are_left(world):
    app, _, w = world
    now = datetime.now(UTC)
    old = now - timedelta(days=cd.STALE_DAYS + 6)
    await store(app, {w.park: [doc("gone", "Old printer notes", "The printer is a Brother.")]}, now=old)
    await store(app, {w.park: [doc("other", "Other tool notes", "The printer is a Brother too.")]}, vendor="othertool", now=old)
    await store(app, {w.park: [doc("fresh", "Switch notes", "The switch sits in the closet.")]}, now=now)
    titles = {h.title for h in await ask(app, w, "printer brother")}
    assert "Old printer notes" not in titles, "dropped: it was not refreshed in the latest report"
    assert "Other tool notes" in titles, "another vendor's records are not this vendor's to drop"


@pytest.mark.asyncio
async def test_another_organizations_documents_are_never_found_and_the_summary_counts_by_client(world):
    app, _, w = world
    await store(
        app,
        {
            w.park: [
                doc("a", "Backup plan", "Nightly backup to the cloud.", kind="document"),
                doc("b", "Server", "Backup server details.", kind="configuration"),
            ]
        },
    )
    await store(app, {w.stranger: [doc("z", "Backup plan", "Backup plan of somebody else entirely.")]})
    hits = await ask(app, w, "backup plan")
    assert all(h.client_id in (w.parent, w.park, w.school) for h in hits)
    assert not any("somebody else" in h.snippet for h in hits)
    async with AsyncSession(app) as db:
        summary = await client_documents_summary(SimpleNamespace(tenant_id=w.parent), db)
    park = next(r for r in summary if r.client_id == w.park)
    assert park.kinds == {"document": 1, "configuration": 1} and park.refreshed_at is not None
    assert all(r.client_id != w.stranger for r in summary)


@pytest.mark.asyncio
async def test_a_question_of_only_unknown_words_or_none_finds_nothing_without_an_error(world):
    app, _, w = world
    assert await ask(app, w, "?!") == []
    assert await ask(app, w, "zzqqxxnothingmatchesthis") == []


@pytest.mark.asyncio
async def test_a_secret_in_a_record_is_not_stored_or_searchable_but_the_rest_of_it_is(world):
    app, owner, w = world
    await store(app, {w.park: [doc("n1", "Router notes", "Router login\nPassword: Zebra-Quartz-77\nThe router is in the closet.")]})
    assert await ask(app, w, "zebra quartz") == []
    assert [h.title for h in await ask(app, w, "router closet")] == ["Router notes"]
    async with owner.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        body = (
            await conn.execute(text("select body from client_documents where tenant_id = :t and external_id = 'n1'"), {"t": w.park})
        ).scalar_one()
    assert "Zebra" not in body and "[redacted]" in body
