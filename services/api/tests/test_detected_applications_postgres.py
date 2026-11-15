"""Detected applications, against a REAL Postgres as the restricted role (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).

CORE reports the apps of a client's Microsoft 365 tenant; they are stored under the client the tenant is mapped to, a person Adds, Ignores or Links each one, and the vendor page counts the linked ones together.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import detected_applications as ep
from app.api.v1.endpoints import vendor_management as vm
from app.db.rls import set_rls_context
from app.services import alias_view
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
GUID = "11111111-aaaa-bbbb-cccc-222222222222"


@pytest.fixture
async def world():
    owner, acme, birch = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"),
            {"i": owner, "n": f"da-owner-{tag}", "s": f"da-owner-{tag}"},
        )
        for tid, n in ((acme, "acme"), (birch, "birch")):
            await conn.execute(
                text("insert into tenants (id, name, slug, mssp_role, parent_tenant_id) values (:i, :n, :s, 'child', :p)"),
                {"i": tid, "n": f"da-{n}-{tag}", "s": f"da-{n}-{tag}", "p": owner},
            )
        await conn.execute(
            text(
                "insert into client_aliases (tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id, ignored, match_source) "
                "values (:p, 'cipp', :g, 'acme', 'acme', :c, false, 'manual')"
            ),
            {"p": owner, "g": GUID, "c": acme},
        )
    alias_view.forget_aliases()
    w = SimpleNamespace(
        owner=owner,
        acme=acme,
        birch=birch,
        engine=engine,
        user=SimpleNamespace(tenant_id=owner, user_id=None, email="hal@goliveoak.com"),
        request=SimpleNamespace(client=None, headers={}),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (owner, acme, birch):
            for table in ("detected_applications", "vendor_history", "vendors"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": t})
        await conn.execute(text("delete from client_aliases where tenant_id = :t"), {"t": owner})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [acme, birch, owner]})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


def report(*apps, client=GUID):
    return ep.AppsReport(vendor="cipp", vendor_client_id=client, items=[ep.AppIn(**a) for a in apps])


LASTPASS = {"app_id": "app-1", "name": "LastPass Login App", "accounts": 47, "scopes": ["User.Read"], "risky": False}
LASTPASS2 = {"app_id": "app-2", "name": "LastPass Provisioning App", "accounts": 47, "scopes": ["Directory.ReadWrite.All"], "risky": True}
ASANA = {"app_id": "app-3", "name": "Asana", "accounts": 1, "scopes": []}


async def ingest(w, *apps, client=GUID):
    async def work(db):
        out = await ep.apply_applications(db, w.owner, report(*apps, client=client))
        await db.commit()
        return out

    return await run(w.owner, work)


async def listing(w, tenant, show="new"):
    return await run(tenant, lambda db: ep.list_applications(tenant, db, w.user, show))


async def test_apps_are_stored_under_the_mapped_client_new_and_waiting_and_an_unmapped_tenant_is_counted_not_stored(world):
    w = world
    got = await ingest(w, LASTPASS, LASTPASS2, ASANA)
    assert got.accepted == 3 and got.unmapped == 0
    out = await listing(w, w.acme)
    assert out.counts == {"new": 3, "added": 0, "linked": 0, "ignored": 0}
    assert {a.name for a in out.apps} == {"LastPass Login App", "LastPass Provisioning App", "Asana"} and all(
        a.source_label == "Microsoft 365" for a in out.apps
    )
    assert next(a for a in out.apps if a.name.startswith("LastPass Prov")).risky
    unmapped = await ingest(w, ASANA, client="99999999-0000-0000-0000-000000000000")
    assert (unmapped.accepted, unmapped.unmapped) == (0, 1)
    assert (await listing(w, w.birch)).apps == [], "another client sees none of it"


async def test_a_second_report_updates_the_counts_and_never_undoes_a_decision(world):
    w = world
    await ingest(w, ASANA)
    app = (await listing(w, w.acme)).apps[0]
    await run(w.acme, lambda db: ep.ignore_application(app.id, w.acme, db, w.user))
    await ingest(w, {**ASANA, "accounts": 5})
    out = await listing(w, w.acme, "ignored")
    assert [(a.name, a.accounts, a.status) for a in out.apps] == [("Asana", 5, "ignored")]
    assert (await listing(w, w.acme)).apps == []


async def test_add_makes_a_vendor_and_adding_a_second_app_of_the_same_name_links_to_it(world):
    w = world
    await ingest(w, ASANA, {"app_id": "app-9", "name": "asana", "accounts": 2})
    first, second = sorted((await listing(w, w.acme)).apps, key=lambda a: a.name)
    added = await run(w.acme, lambda db: ep.add_application(first.id, w.acme, db, w.user))
    assert added.status == "added" and added.vendor_id is not None
    again = await run(w.acme, lambda db: ep.add_application(second.id, w.acme, db, w.user))
    assert (
        again.status == "linked" and again.vendor_id == added.vendor_id
    ), "same name: joined to the vendor that is there, not a second vendor"
    vendors = await run(w.acme, lambda db: vm.list_vendors(w.acme, db, w.user, False))
    assert [v.name for v in vendors.vendors] == ["Asana"]
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.add_application(first.id, w.acme, db, w.user))
    assert e.value.status_code == 409


async def test_link_joins_several_apps_to_one_vendor_and_the_vendor_page_adds_up_their_accounts(world):
    w = world
    await ingest(w, LASTPASS, LASTPASS2)
    vendor = await run(w.acme, lambda db: vm.create_vendor(vm.VendorIn(name="LastPass"), w.request, w.acme, db, w.user))
    for app in (await listing(w, w.acme)).apps:
        done = await run(w.acme, lambda db, a=app: ep.link_application(a.id, ep.LinkIn(vendor_id=vendor.id), w.acme, db, w.user))
        assert done.status == "linked" and done.vendor_name == "LastPass"
    detail = await run(w.acme, lambda db: vm.get_vendor(vendor.id, w.acme, db, w.user))
    assert sorted(a.name for a in detail.applications) == ["LastPass Login App", "LastPass Provisioning App"]
    assert [h.action for h in detail.history].count("application_linked") == 2
    assert (await listing(w, w.acme)).counts["linked"] == 2 and (await listing(w, w.acme)).apps == []
    back = await run(w.acme, lambda db: ep.restore_application((await_first(detail)).id, w.acme, db, w.user))
    assert back.status == "new" and back.vendor_id is None


def await_first(detail):
    return detail.applications[0]


async def test_a_vendor_of_another_client_cannot_be_linked_and_another_client_cannot_decide_on_the_app(world):
    w = world
    await ingest(w, ASANA)
    app = (await listing(w, w.acme)).apps[0]
    theirs = await run(w.birch, lambda db: vm.create_vendor(vm.VendorIn(name="Birch only"), w.request, w.birch, db, w.user))
    with pytest.raises(HTTPException) as no_vendor:
        await run(w.acme, lambda db: ep.link_application(app.id, ep.LinkIn(vendor_id=theirs.id), w.acme, db, w.user))
    assert no_vendor.value.status_code == 404
    with pytest.raises(HTTPException) as no_app:
        await run(w.birch, lambda db: ep.ignore_application(app.id, w.birch, db, w.user))
    assert no_app.value.status_code == 404
