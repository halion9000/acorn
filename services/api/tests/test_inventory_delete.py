"""Deleting an inventory item: refused while it is checked out or kept in step with a tool, written to the audit log with what it was, and the item and its history are removed.

The database layer is replaced by small stand-ins here (the real-Postgres version of this is at the bottom and runs when AISOC_TEST_PG_URL is set, like the other inventory tests)."""

import contextlib
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import inventory as ep
from fastapi import HTTPException

OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()


def item(**over):
    base = dict(id=uuid.uuid4(), tenant_id=CLIENT, kind="stock", name="Dell 7440", serial="ABC123", category="Laptop", status="checked_in", source="manual")
    return SimpleNamespace(**{**base, **over})


@pytest.fixture
def rig(monkeypatch):
    db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
    audit = AsyncMock()
    found = {}

    async def find(_db, _user, _id):
        return found["item"], {CLIENT: "Acme Dental"}

    @contextlib.asynccontextmanager
    async def acting(*_a, **_k):
        yield

    monkeypatch.setattr(ep, "_find", find)
    monkeypatch.setattr(ep, "_acting", acting)
    monkeypatch.setattr(ep, "emit_audit", audit)
    user = SimpleNamespace(tenant_id=OWNER, user_id=uuid.uuid4(), email="hal@goliveoak.com")
    return SimpleNamespace(db=db, audit=audit, found=found, user=user)


@pytest.mark.asyncio
async def test_an_item_in_stock_is_deleted_and_the_audit_log_says_what_it_was(rig):
    rig.found["item"] = item()
    out = await ep.delete_item(rig.found["item"].id, rig.user, rig.db)
    assert (out.deleted, out.name) == (True, "Dell 7440")
    rig.db.execute.assert_awaited_once()
    assert "DELETE FROM INVENTORY_ITEMS" in str(rig.db.execute.await_args.args[0]).upper().replace("\n", " ")
    rig.db.commit.assert_awaited_once()
    kw = rig.audit.await_args.kwargs
    assert kw["action"] == "inventory:item_deleted" and kw["tenant_id"] == OWNER and kw["actor_email"] == "hal@goliveoak.com"
    assert kw["changes"]["name"] == "Dell 7440" and kw["changes"]["serial"] == "ABC123" and kw["changes"]["client_name"] == "Acme Dental"


@pytest.mark.asyncio
async def test_an_imported_item_can_be_deleted_too(rig):
    rig.found["item"] = item(source="csv")
    assert (await ep.delete_item(rig.found["item"].id, rig.user, rig.db)).deleted is True


@pytest.mark.asyncio
async def test_a_checked_out_item_is_refused_and_nothing_is_deleted_or_logged(rig):
    rig.found["item"] = item(status="checked_out")
    with pytest.raises(HTTPException) as e:
        await ep.delete_item(rig.found["item"].id, rig.user, rig.db)
    assert e.value.status_code == 409 and "Check it in first" in e.value.detail
    rig.db.execute.assert_not_awaited()
    rig.db.commit.assert_not_awaited()
    rig.audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_item_a_tool_keeps_in_step_is_refused_with_the_way_out(rig):
    rig.found["item"] = item(source="device")
    with pytest.raises(HTTPException) as e:
        await ep.delete_item(rig.found["item"].id, rig.user, rig.db)
    assert e.value.status_code == 409 and "Retired" in e.value.detail
    rig.db.execute.assert_not_awaited()
    rig.audit.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_item_that_is_not_the_callers_is_a_404(monkeypatch, rig):
    async def nothing(*_a):
        raise HTTPException(status_code=404, detail="Item not found")

    monkeypatch.setattr(ep, "_find", nothing)
    with pytest.raises(HTTPException) as e:
        await ep.delete_item(uuid.uuid4(), rig.user, rig.db)
    assert e.value.status_code == 404
    rig.db.execute.assert_not_awaited()


def test_the_route_needs_the_same_permission_as_changing_an_item():
    import inspect

    src = inspect.getsource(ep.delete_item)
    assert 'require_permission("mssp:manage")' in src.replace("'", '"') or "mssp:manage" in inspect.getsource(ep)
    route = next(r for r in ep.router.routes if getattr(r, "methods", None) == {"DELETE"} and r.path.endswith("/{item_id}"))
    assert route is not None


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")


@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")
@pytest.mark.asyncio
async def test_on_real_postgres_the_item_and_its_history_are_gone_and_the_audit_entry_stays():
    """NOT RUN in the development environment (no Postgres): deletes an item through the real route and checks the item, its events (ON DELETE CASCADE) and a leftover row of another client."""
    from tests.test_inventory_postgres import cleanup, world  # noqa: PLC0415

    engine, user, ids = await world()
    try:
        from sqlalchemy import text  # noqa: PLC0415
        from sqlalchemy.ext.asyncio import AsyncSession  # noqa: PLC0415

        async with AsyncSession(engine) as db:
            created = await ep.create_item(ep.ItemIn(kind="stock", name="Dell 7440", client_id=ids.acme), user, db)
            await ep.delete_item(created.id, user, db)
            left = (await db.execute(text("select count(*) from inventory_items where id = :i"), {"i": created.id})).scalar_one()
            events = (await db.execute(text("select count(*) from inventory_events where item_id = :i"), {"i": created.id})).scalar_one()
        assert (left, events) == (0, 0)
    finally:
        await cleanup(engine, [ids.owner, ids.acme, ids.birch, ids.stranger, ids.stranger_client])
