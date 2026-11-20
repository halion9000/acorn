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


def row(client, name, item, billed, counted, parts=()):
    return SimpleNamespace(
        client_id=client, client_name=name, invoice_item=item, billed=billed, counted=counted, difference=counted - billed, parts=list(parts)
    )


@pytest.fixture
def differences(monkeypatch, world):
    rows = [
        row(world.mapped, "Acme Dental", "Microsoft 365 Business Premium", 10, 12, [{"source": "cipp", "item": "Business Premium", "count": 9}, {"source": "cipp", "item": "Business Standard", "count": 3}]),
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
    assert [(p.source, p.item, p.count) for p in out.rows[0].parts] == [("cipp", "Business Premium", 9), ("cipp", "Business Standard", 3)], "the counted number shows what it is made of"
    assert out.rows[1].parts == []


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


def test_for_a_day_after_a_push_that_worked_the_line_counts_the_pushed_quantity_as_billed():
    from datetime import UTC, datetime, timedelta

    from app.api.v1.endpoints.billing_sync import billed_after_push

    now = datetime(2026, 11, 20, 15, tzinfo=UTC)
    soon = now - timedelta(hours=2)
    assert billed_after_push(627, 838, "done", 838, soon, now) == (838, 0), "fixed: no difference left until CORE reads HaloPSA again"
    assert billed_after_push(627, 900, "done", 838, soon, now) == (838, 62), "the tool count moved on after the push"
    assert billed_after_push(627, 838, "done", 838, now - timedelta(hours=25), now) == (627, 211), "after a day CORE's own reading is trusted again"
    assert billed_after_push(627, 838, "failed", 838, soon, now) == (627, 211), "a push that failed changes nothing"
    assert billed_after_push(627, 838, "pending", 838, soon, now) == (627, 211)
    assert billed_after_push(627, 838, None, None, None, now) == (627, 211)


@needs_pg
@pytest.mark.asyncio
async def test_refresh_leaves_one_request_for_core_that_its_usual_claim_hands_over_once_and_the_list_says_when_counts_were_last_read(world, differences):
    from app.api.v1.endpoints.inbox_core_feed import claim_sync_requests_for

    asked = await with_db(world.owner, lambda db: ep.request_refresh(world.user, db))
    assert asked["vendor"] == "billing-counts" and asked["requested_at"]

    async def claim(db):
        got = await claim_sync_requests_for(db, world.owner)
        await db.commit()
        return got

    assert "billing-counts" in await with_db(world.owner, claim), "CORE's claim hands the request over"
    assert "billing-counts" not in await with_db(world.owner, claim), "and only once"
    out = await with_db(world.owner, lambda db: ep.list_sync(world.user, db, False))
    assert hasattr(out, "counts_read_at"), "the list carries the time the counts were last read (empty when no client has any)"


def test_the_link_of_a_row_is_linked_when_a_line_carries_a_license_not_linked_when_only_a_license_has_the_name_and_na_when_there_is_none():
    from app.api.v1.endpoints.billing_sync import link_status

    data = {
        "licenses": [
            {"id": 7, "client_id": "219", "name": "Datto SaaS Google Users - acme.com", "active": True},
            {"id": 8, "client_id": "219", "name": "Sentinel Endpoints", "active": True},
            {"id": 9, "client_id": "300", "name": "Datto SaaS Google Users - other.com", "active": True},
        ],
        "lines": [
            {"client_id": "219", "invoice_id": 1, "item": "Google Workspace Backup", "licence_ids": [7]},
            {"client_id": "219", "invoice_id": 1, "item": "Sentinel Endpoints", "licence_ids": []},
            {"client_id": "219", "invoice_id": 1, "item": "Managed Services", "licence_ids": []},
        ],
    }
    assert link_status("219", "Google Workspace Backup", data) == ("linked", 7), "the line carries the license id"
    assert link_status("219", "Sentinel Endpoints", data) == ("not_linked", 8), "the license exists but no line is tied to it"
    assert link_status("219", "Managed Services", data) == ("na", None)
    assert link_status("300", "Google Workspace Backup", data) == ("na", None), "another client's license and lines do not count"
    assert link_status("219", "Sentinel Endpoints", None) == ("unknown", None)
    assert link_status(None, "Sentinel Endpoints", data) == ("unknown", None)
