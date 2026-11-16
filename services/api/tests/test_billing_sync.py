"""Billing sync: the billing role, and approving, hiding and listing license-count differences.

The role first (pure), then the endpoints against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database). The differences themselves are what /billing/reconcile
already finds (tested elsewhere), so here they are supplied directly and what is tested is what the sync does with them.
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import billing_sync as ep
from app.core.security import ROLE_PERMISSIONS, has_permission, permission_in
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_the_billing_role_reads_what_a_viewer_reads_and_may_push_but_nothing_more():
    assert has_permission("billing", "billing:push") and has_permission("billing", "billing:view")
    for p in ROLE_PERMISSIONS["viewer"]:
        assert has_permission("billing", p), f"billing lacks what a viewer has: {p}"
    for p in (
        "finance:view",
        "finance:write",
        "alerts:write",
        "cases:write",
        "connectors:write",
        "settings_workspace:manage",
        "billing:write",
    ):
        assert not has_permission("billing", p), f"billing must not hold {p}"


def test_the_push_permission_is_held_by_the_billing_role_and_wildcards_only_and_implies_nothing():
    assert not any(has_permission(r, "billing:push") for r in ("viewer", "soc_analyst", "threat_hunter", "soc_lead", "api_service"))
    assert (
        permission_in(["billing:*"], "billing:push")
        and permission_in(["*"], "billing:push")
        and permission_in(["billing:push"], "billing:push")
    )
    assert not permission_in(["billing:push"], "alerts:read") and not permission_in(["alerts:read"], "billing:push")


PG_URL, APP_URL = os.environ.get("AISOC_TEST_PG_URL"), os.environ.get("AISOC_TEST_PG_APP_URL")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    owner, mapped, unmapped = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name in ((owner, "owner"), (mapped, "Acme Dental"), (unmapped, "Birch Law")):
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": name, "s": f"bs-{tid.hex[:8]}"}
            )
        await conn.execute(
            text(
                "insert into client_aliases (id, tenant_id, vendor, vendor_client_id, vendor_client_name, normalized_name, child_tenant_id) values (gen_random_uuid(), :o, 'halopsa', '57', 'Acme Dental, Inc.', 'acmedentalinc', :c)"
            ),
            {"o": owner, "c": mapped},
        )
    yield SimpleNamespace(
        owner=owner, mapped=mapped, unmapped=unmapped, user=SimpleNamespace(tenant_id=owner, user_id=None, email="billing@goliveoak.com")
    )
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in ("billing_sync_items", "vendor_actions", "client_aliases"):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": owner})
        await conn.execute(text("delete from audit_log where tenant_id = :t"), {"t": owner})
        for tid in (owner, mapped, unmapped):
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


def row(client, name, item, billed, counted):
    return SimpleNamespace(
        client_id=client, client_name=name, invoice_item=item, billed=billed, counted=counted, difference=counted - billed
    )


@pytest.fixture
def differences(monkeypatch, world):
    rows = [
        row(world.mapped, "Acme Dental", "Microsoft 365 Business Premium", 10, 12),
        row(world.mapped, "Acme Dental", "Windows workstations", 20, 20),
        row(world.unmapped, "Birch Law", "Microsoft 365 Business Premium", 5, 4),
    ]

    async def fake(user, db):
        return rows

    monkeypatch.setattr(ep, "_rows", fake)
    return rows


@needs_pg
@pytest.mark.asyncio
async def test_the_list_shows_only_differences_and_says_which_clients_can_be_pushed(world, differences):
    out = await with_db(world.owner, lambda db: ep.list_sync(world.user, db, False))
    assert [(r.client_name, r.invoice_item, r.difference, r.can_push, r.push.status) for r in out.rows] == [
        ("Acme Dental", "Microsoft 365 Business Premium", 2, True, "none"),
        ("Birch Law", "Microsoft 365 Business Premium", -1, False, "none"),
    ]
    assert out.hidden == 0


@needs_pg
@pytest.mark.asyncio
async def test_approving_queues_a_push_of_the_counted_quantity_for_core_and_asks_once(world, differences):
    req = SimpleNamespace(client=None, headers={})
    item = ep.ItemIn(client_id=world.mapped, invoice_item="Microsoft 365 Business Premium")
    first = await with_db(world.owner, lambda db: ep.approve(ep.ApproveIn(items=[item]), req, world.user, db))
    assert [(x.ok, x.detail) for x in first] == [(True, "Queued: set to 12 (was 10).")]

    async def actions(db):
        return (
            await db.execute(text("select vendor, action, params, status from vendor_actions where tenant_id = :t"), {"t": world.owner})
        ).all()

    (vendor, action, params, status) = (await with_db(world.owner, actions))[0]
    assert (vendor, action, status) == ("core", "halo_billing_update", "pending")
    assert params == {
        "halo_client_id": "57",
        "halo_client_name": "Acme Dental, Inc.",
        "invoice_item": "Microsoft 365 Business Premium",
        "quantity": 12,
        "previous": 10,
    }

    again = await with_db(world.owner, lambda db: ep.approve(ep.ApproveIn(items=[item]), req, world.user, db))
    assert [(x.ok, x.detail) for x in again] == [(False, "A push for this line is still waiting.")]
    assert len(await with_db(world.owner, actions)) == 1, "a second push was not queued"

    listed = await with_db(world.owner, lambda db: ep.list_sync(world.user, db, False))
    acme = next(r for r in listed.rows if r.client_name == "Acme Dental")
    assert (acme.push.status, acme.push.quantity, acme.push.by) == ("pending", 12, "billing@goliveoak.com")


@needs_pg
@pytest.mark.asyncio
async def test_a_line_that_matches_a_client_with_no_halopsa_mapping_or_a_line_nobody_has_is_refused(world, differences):
    req = SimpleNamespace(client=None, headers={})
    items = [
        ep.ItemIn(client_id=world.unmapped, invoice_item="Microsoft 365 Business Premium"),
        ep.ItemIn(client_id=world.mapped, invoice_item="Windows workstations"),
        ep.ItemIn(client_id=world.mapped, invoice_item="Not a line"),
    ]
    out = await with_db(world.owner, lambda db: ep.approve(ep.ApproveIn(items=items), req, world.user, db))
    assert [(x.ok, x.detail) for x in out] == [
        (False, "This client is not mapped to a HaloPSA client."),
        (False, "This line no longer differs."),
        (False, "This line no longer differs."),
    ]
    count = await with_db(
        world.owner, lambda db: db.execute(text("select count(*) from vendor_actions where tenant_id = :t"), {"t": world.owner})
    )
    assert count.scalar_one() == 0, "nothing was queued"


@needs_pg
@pytest.mark.asyncio
async def test_hiding_keeps_a_line_out_of_the_list_until_it_is_unhidden_and_changes_nothing_at_halopsa(world, differences):
    req = SimpleNamespace(client=None, headers={})
    item = ep.ItemIn(client_id=world.mapped, invoice_item="Microsoft 365 Business Premium")
    assert await with_db(world.owner, lambda db: ep.hide(ep.HideIn(items=[item]), req, world.user, db)) == {"changed": 1}
    shown = await with_db(world.owner, lambda db: ep.list_sync(world.user, db, False))
    assert [r.client_name for r in shown.rows] == ["Birch Law"] and shown.hidden == 1
    everything = await with_db(world.owner, lambda db: ep.list_sync(world.user, db, True))
    assert [(r.client_name, r.hidden) for r in everything.rows] == [("Acme Dental", True), ("Birch Law", False)]
    await with_db(world.owner, lambda db: ep.hide(ep.HideIn(items=[item], hidden=False), req, world.user, db))
    back = await with_db(world.owner, lambda db: ep.list_sync(world.user, db, False))
    assert len(back.rows) == 2 and back.hidden == 0
    queued = await with_db(
        world.owner, lambda db: db.execute(text("select count(*) from vendor_actions where tenant_id = :t"), {"t": world.owner})
    )
    assert queued.scalar_one() == 0
