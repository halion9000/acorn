"""The roadmap: the checked file entries, the repository file itself, and (against a REAL Postgres as the restricted role, AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL) syncing, priority and isolation."""

import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import roadmap as ep
from app.db.rls import set_rls_context
from app.services import roadmap_sync as rs
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)
FILE = Path(__file__).resolve().parents[3] / "docs" / "ROADMAP_ITEMS.json"


def test_clean_refuses_unknown_status_or_needs_and_missing_key_and_trims_text():
    with pytest.raises(ValueError):
        rs.clean({"key": "a", "title": "x", "status": "done"})
    with pytest.raises(ValueError):
        rs.clean({"key": "a", "title": "x", "needs": "someone"})
    with pytest.raises(ValueError):
        rs.clean({"title": "no key"})
    out = rs.clean({"key": "k" * 200, "title": "t" * 500})
    assert len(out["key"]) == 80 and len(out["title"]) == 200
    assert (out["status"], out["needs"], out["area"]) == ("not_started", "claude", "General")


def test_the_repository_file_is_valid_with_unique_keys_and_nothing_started_without_a_reason():
    entries = json.loads(FILE.read_text(encoding="utf-8"))
    cleaned = [rs.clean(e) for e in entries]
    assert len({c["key"] for c in cleaned}) == len(cleaned) >= 30
    assert {c["needs"] for c in cleaned} == {"claude", "signoff", "hal"}
    assert {c["status"] for c in cleaned} == {"new", "not_started", "in_progress", "completed"}
    assert all(c["note"] for c in cleaned if c["needs"] == "hal"), "an item that waits on a person must say what for"


def test_open_work_sorts_before_finished_and_urgent_before_normal():
    def row(status, priority, n):
        return SimpleNamespace(status=status, priority=priority, created_at=n, completed_at=n, updated_at=n)

    rows = [
        row("completed", "high", 1),
        row("not_started", "low", 2),
        row("not_started", "high", 3),
        row("in_progress", "low", 4),
        row("new", "normal", 5),
    ]
    assert [(r.status, r.priority) for r in ep._sorted(rows)] == [
        ("in_progress", "low"),
        ("new", "normal"),
        ("not_started", "high"),
        ("not_started", "low"),
        ("completed", "high"),
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
                text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": tid, "n": name, "s": f"rm-{tag}-{str(tid)[:6]}"}
            )
    yield SimpleNamespace(acme=acme, birch=birch)
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


def user(tenant):
    return SimpleNamespace(tenant_id=tenant, user_id=None, email="hal@goliveoak.com")


@needs_pg
@pytest.mark.asyncio
async def test_sync_adds_updates_the_file_owned_fields_but_never_the_priority_or_the_pages_own_items(world):
    w = world
    first = [
        {"key": "a", "title": "Item A", "status": "not_started"},
        {"key": "b", "title": "Item B", "status": "in_progress", "needs": "hal", "note": "x"},
    ]
    assert await run(w.acme, lambda db: rs.sync(db, w.acme, first)) == {"added": 2, "changed": 0, "unchanged": 0}
    mine = await run(w.acme, lambda db: ep.add_item(ep.ItemIn(title="My own idea"), db, user(w.acme)))
    items = (await run(w.acme, lambda db: ep.list_items(db, user(w.acme)))).items
    a = next(i for i in items if i.key == "a")
    await run(w.acme, lambda db: ep.update_item(a.id, ep.ItemPatch(priority="high"), db, user(w.acme)))
    second = [{"key": "a", "title": "Item A renamed", "status": "completed", "completed_ref": "abc123"}, first[1]]
    assert await run(w.acme, lambda db: rs.sync(db, w.acme, second)) == {"added": 0, "changed": 1, "unchanged": 1}
    out = await run(w.acme, lambda db: ep.list_items(db, user(w.acme)))
    a2 = next(i for i in out.items if i.key == "a")
    assert (a2.title, a2.status, a2.priority, a2.completed_ref) == (
        "Item A renamed",
        "completed",
        "high",
        "abc123",
    ) and a2.completed_at is not None
    assert next(i for i in out.items if i.id == mine.id).key is None
    assert out.counts == {"new": 1, "not_started": 0, "in_progress": 1, "completed": 1}
    assert out.items[-1].key == "a", "the finished item is last"
    await run(w.acme, lambda db: rs.sync(db, w.acme, [first[1]]))
    assert len((await run(w.acme, lambda db: ep.list_items(db, user(w.acme)))).items) == 3, "a key that leaves the file stays"


@needs_pg
@pytest.mark.asyncio
async def test_a_person_can_move_status_and_needs_and_one_organization_never_sees_anothers_items(world):
    w = world
    made = await run(w.acme, lambda db: ep.add_item(ep.ItemIn(title="Acme only", needs="hal"), db, user(w.acme)))
    moved = await run(
        w.acme, lambda db: ep.update_item(made.id, ep.ItemPatch(status="in_progress", needs="claude", note="started"), db, user(w.acme))
    )
    assert (moved.status, moved.needs, moved.note) == ("in_progress", "claude", "started")
    back = await run(w.acme, lambda db: ep.update_item(made.id, ep.ItemPatch(status="completed"), db, user(w.acme)))
    assert back.completed_at is not None
    reopened = await run(w.acme, lambda db: ep.update_item(made.id, ep.ItemPatch(status="not_started"), db, user(w.acme)))
    assert reopened.completed_at is None
    assert (await run(w.birch, lambda db: ep.list_items(db, user(w.birch)))).items == []
    with pytest.raises(HTTPException) as e:
        await run(w.birch, lambda db: ep.update_item(made.id, ep.ItemPatch(priority="low"), db, user(w.birch)))
    assert e.value.status_code == 404


@needs_pg
@pytest.mark.asyncio
async def test_a_removed_item_is_hidden_and_never_brought_back_and_a_status_a_person_set_is_kept(world):
    w = world
    entries = [{"key": "a", "title": "Item A", "status": "in_progress"}, {"key": "b", "title": "Item B", "status": "not_started"}]
    await run(w.acme, lambda db: rs.sync(db, w.acme, entries))
    items = (await run(w.acme, lambda db: ep.list_items(db, user(w.acme)))).items
    a = next(i for i in items if i.key == "a")
    b = next(i for i in items if i.key == "b")
    await run(w.acme, lambda db: ep.remove_item(b.id, db, user(w.acme)))
    await run(w.acme, lambda db: ep.update_item(a.id, ep.ItemPatch(status="completed"), db, user(w.acme)))
    out = await run(w.acme, lambda db: rs.sync(db, w.acme, entries))
    assert out == {
        "added": 0,
        "changed": 0,
        "unchanged": 2,
    }, "the file still says in progress and not started, and neither is brought back or reset"
    listed = await run(w.acme, lambda db: ep.list_items(db, user(w.acme)))
    assert [(i.key, i.status) for i in listed.items] == [("a", "completed")]
    assert listed.counts["not_started"] == 0
    with pytest.raises(HTTPException) as e:
        await run(w.acme, lambda db: ep.remove_item(b.id, db, user(w.acme)))
    assert e.value.status_code == 404, "already removed"
    with pytest.raises(HTTPException) as e2:
        await run(w.birch, lambda db: ep.remove_item(a.id, db, user(w.birch)))
    assert e2.value.status_code == 404, "another organization cannot remove it"
    done = [{"key": "a", "title": "Item A", "status": "in_progress"}]
    await run(w.acme, lambda db: rs.sync(db, w.acme, [{**done[0], "status": "completed", "completed_ref": "abc"}]))
    again = (await run(w.acme, lambda db: ep.list_items(db, user(w.acme)))).items[0]
    assert again.status == "completed" and again.completed_ref == "abc"
