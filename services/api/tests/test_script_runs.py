"""The script log: what each state reads as, one log line from a request row, and (on a REAL Postgres, AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL) the list across the organization and its clients."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import script_runs as ep
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def row(status="done", created_minutes_ago=5, claimed=True, message=None, requested_by=None, params=None, alert_id=None):
    created = NOW - timedelta(minutes=created_minutes_ago)
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        created_at=created,
        claimed_at=created + timedelta(minutes=1) if claimed else None,
        finished_at=created + timedelta(minutes=2) if status in ("done", "failed") else None,
        result_message=message,
        requested_by=requested_by,
        alert_id=alert_id,
        params={"script_name": "Disk Space Scan", "device": "PC-01", "alert_title": "Low disk space", **(params or {})},
    )


def test_each_state_falls_under_one_of_three_outcomes() -> None:
    assert ep.outcome_of("done") == "done"
    assert ep.outcome_of("failed") == "failed" and ep.outcome_of("expired") == "failed"
    assert ep.outcome_of("pending") == "waiting" and ep.outcome_of("claimed") == "waiting"


def test_a_finished_script_shows_its_script_device_alert_and_result() -> None:
    item = ep.to_item(row("done", message="Script finished with exit code 0.", requested_by=uuid.uuid4()), "Acme Dental", NOW)
    assert (item.status, item.outcome, item.script, item.device, item.client_name, item.by) == ("done", "done", "Disk Space Scan", "PC-01", "Acme Dental", "person")
    assert item.alert_title == "Low disk space" and item.message == "Script finished with exit code 0."
    assert item.finished_at is not None


def test_a_request_nobody_collected_reads_expired_and_says_why_in_words() -> None:
    item = ep.to_item(row("pending", created_minutes_ago=45, claimed=False), None, NOW)
    assert (item.status, item.outcome) == ("expired", "failed")
    assert "never run" in (item.message or "") and "CORE was off" in (item.message or "")


def test_a_request_still_inside_its_time_is_waiting_and_a_claimed_one_that_never_reported_is_failed() -> None:
    assert ep.to_item(row("pending", created_minutes_ago=5, claimed=False), None, NOW).outcome == "waiting"
    assert ep.to_item(row("claimed", created_minutes_ago=5), None, NOW).outcome == "waiting"
    stale = ep.to_item(row("claimed", created_minutes_ago=60), None, NOW)
    assert (stale.status, stale.outcome) == ("failed", "failed")
    assert "never reported" in (stale.message or "")


def test_a_failure_keeps_the_message_core_gave_and_a_rule_is_told_from_a_person() -> None:
    item = ep.to_item(row("failed", message="NinjaOne answered 404: no such device.", requested_by=None), None, NOW)
    assert item.message == "NinjaOne answered 404: no such device." and item.by == "rule"


def test_a_missing_script_name_and_an_overlong_message_are_handled() -> None:
    item = ep.to_item(row("failed", message="x" * 2000, params={"script_name": None, "script_id": 42}), None, NOW)
    assert item.script == "42" and len(item.message or "") == ep.MESSAGE_CHARS


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")


@pytest.fixture
async def world():
    owner, acme, birch, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent in ((owner, "owner", None), (acme, "acme", owner), (birch, "birch", owner), (stranger, "stranger", None)):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, :n, :s, :p)"),
                {"i": tid, "n": f"sr-{name}", "s": f"sr-{name}-{tid.hex[:8]}", "p": parent},
            )
    yield SimpleNamespace(owner=owner, acme=acme, birch=birch, stranger=stranger, engine=engine, user=SimpleNamespace(tenant_id=owner, user_id=None))
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        ids = [owner, acme, birch, stranger]
        await conn.execute(text("delete from vendor_actions where tenant_id = any(:t)"), {"t": ids})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": ids})
    await engine.dispose()


async def queue(w, tenant, status, device, minutes_ago=5, action="run_script", vendor="core", message=None, requested_by=None):
    async with w.engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text(
                "insert into vendor_actions (id, tenant_id, vendor, incident_uid, action, params, status, result_message, requested_by, created_at) "
                "values (:i, :t, :v, 'u', :a, cast(:p as jsonb), :s, :m, :r, :c)"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant,
                "v": vendor,
                "a": action,
                "p": '{"script_name": "Disk Space Scan", "device": "%s"}' % device,
                "s": status,
                "m": message,
                "r": requested_by,
                "c": datetime.now(UTC) - timedelta(minutes=minutes_ago),
            },
        )


async def run(w, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_the_log_lists_the_organization_and_its_clients_newest_first_with_counts_and_no_stranger(world):
    w = world
    await queue(w, w.owner, "done", "OWN-1", minutes_ago=50, message="ok")
    await queue(w, w.acme, "failed", "ACME-1", minutes_ago=20, message="NinjaOne answered 404")
    await queue(w, w.birch, "pending", "BIRCH-1", minutes_ago=3)
    await queue(w, w.acme, "pending", "ACME-2", minutes_ago=90)  # nobody collected it: expired
    await queue(w, w.stranger, "done", "STRANGER-1", minutes_ago=5)
    await queue(w, w.acme, "done", "NOT-A-SCRIPT", minutes_ago=5, action="create_ticket", vendor="core")  # same vendor, other action
    out = await run(w, lambda db: ep.list_script_runs(w.user, db, None, None, 30))
    devices = [i.device for i in out.items]
    assert "STRANGER-1" not in devices and "NOT-A-SCRIPT" not in devices
    assert [i.device for i in out.items] == ["BIRCH-1", "ACME-1", "OWN-1", "ACME-2"], "newest request first"
    assert (out.done, out.failed, out.waiting, out.total) == (1, 2, 1, 4)
    by_device = {i.device: i for i in out.items}
    assert by_device["ACME-1"].client_name == "sr-acme" and by_device["ACME-1"].message == "NinjaOne answered 404"
    assert by_device["ACME-2"].status == "expired" and by_device["ACME-2"].outcome == "failed"


@needs_pg
@pytest.mark.asyncio
async def test_the_log_can_be_cut_to_one_client_or_one_outcome_and_an_unknown_client_is_404(world):
    from fastapi import HTTPException

    w = world
    await queue(w, w.acme, "done", "ACME-1")
    await queue(w, w.acme, "failed", "ACME-2", message="boom")
    await queue(w, w.birch, "done", "BIRCH-1")
    only_acme = await run(w, lambda db: ep.list_script_runs(w.user, db, w.acme, None, 30))
    assert sorted(i.device for i in only_acme.items) == ["ACME-1", "ACME-2"]
    failed = await run(w, lambda db: ep.list_script_runs(w.user, db, None, "failed", 30))
    assert [i.device for i in failed.items] == ["ACME-2"] and failed.total == 1
    assert (failed.done, failed.failed) == (2, 1), "the counts ignore the outcome filter, so the tabs keep their numbers"
    with pytest.raises(HTTPException) as err:
        await run(w, lambda db: ep.list_script_runs(w.user, db, w.stranger, None, 30))
    assert err.value.status_code == 404


@needs_pg
@pytest.mark.asyncio
async def test_a_request_older_than_the_window_is_left_out(world):
    w = world
    await queue(w, w.acme, "done", "OLD", minutes_ago=60 * 24 * 40)
    await queue(w, w.acme, "done", "NEW", minutes_ago=5)
    out = await run(w, lambda db: ep.list_script_runs(w.user, db, None, None, 30))
    assert [i.device for i in out.items] == ["NEW"]
