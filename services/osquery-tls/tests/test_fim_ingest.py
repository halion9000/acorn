"""File-integrity rows that osquery sends are stored for the /fim pages (they were forwarded to ingest only, so the pages were always empty)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from app.models.fim_event import FimEvent
from app.models.node import OsqueryNode
from app.services.fim_rows import fim_event_from
from sqlalchemy import select

AUTH = {"Authorization": "Bearer test-api-token"}
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)


def _row(**over):
    base = {"target_path": "/etc/passwd", "action": "UPDATED", "md5": "d41d8cd98f00b204e9800998ecf8427e", "sha256": "e3b0c442", "time": "1793880000", "uid": "0"}
    base.update(over)
    return base


def _build(row, entry=None):
    return fim_event_from(row, entry=entry or {}, node_key="nk", hostname="web-1", tenant_id="acme", now=NOW)


def test_a_file_events_row_becomes_a_fim_event_with_its_hashes_and_time():
    e = _build(_row())
    assert (e.tenant_id, e.node_key, e.hostname, e.target_path, e.action) == ("acme", "nk", "web-1", "/etc/passwd", "UPDATED")
    assert e.md5 == "d41d8cd98f00b204e9800998ecf8427e" and e.sha256 == "e3b0c442"
    assert e.event_time == datetime.fromtimestamp(1793880000, tz=UTC)


def test_rows_that_are_not_file_events_are_ignored():
    for row in ({}, {"pid": "1", "name": "evil", "path": "/tmp/evil"}, {"target_path": "/etc/passwd"}, {"target_path": "", "action": "UPDATED"}, {"target_path": "/x", "action": "added"}, "x", None, 5, []):
        assert _build(row) is None, row


def test_the_time_comes_from_the_row_then_the_entry_then_now_and_garbage_never_raises():
    assert _build(_row(time=""), entry={"unixTime": 1793880100}).event_time == datetime.fromtimestamp(1793880100, tz=UTC)
    assert _build(_row(time="soon"), entry={"unixTime": "never"}).event_time == NOW
    assert _build(_row(time="99999999999999999999")).event_time == NOW
    assert _build(_row(pid="abc", ppid=None)).pid is None


def test_the_action_is_read_whatever_its_case_and_long_values_are_cut():
    e = _build(_row(action="created", target_path="/a" * 3000, md5="m" * 200))
    assert e.action == "CREATED" and len(e.target_path) == 4000 and len(e.md5) == 64


async def _enroll(client, host):
    r = await client.post("/api/v1/osquery/enroll", json={"enroll_secret": "test-enroll-secret", "host_identifier": host})
    return r.json()["node_key"]


@pytest.mark.asyncio
async def test_a_result_batch_stores_only_its_file_rows_and_still_forwards_everything(client, db_session):
    key = await _enroll(client, "fim-host-1")
    entries = [
        {"name": "pack_aisoc-fim-baseline_passwd_changes", "unixTime": 1793880000, "columns": _row()},
        {"name": "pack_aisoc-fim-baseline_sudoers_changes", "unixTime": 1793880001, "columns": _row(target_path="/etc/sudoers.d/x", action="CREATED")},
        {"name": "logged_in_users", "unixTime": 1793880002, "columns": {"user": "root", "tty": "pts/0"}},
    ]
    with patch("app.api.v1.endpoints.log.forward_events", new=AsyncMock()) as fwd:
        r = await client.post("/api/v1/osquery/log", json={"node_key": key, "log_type": "result", "data": json.dumps(entries)})
    assert r.status_code == 200
    assert len(fwd.call_args[0][0]) == 3, "every row is still forwarded to ingest"
    stored = (await db_session.execute(select(FimEvent).order_by(FimEvent.target_path))).scalars().all()
    assert [(e.target_path, e.action, e.hostname) for e in stored] == [("/etc/passwd", "UPDATED", "fim-host-1"), ("/etc/sudoers.d/x", "CREATED", "fim-host-1")]
    node = (await db_session.execute(select(OsqueryNode).where(OsqueryNode.host_identifier == "fim-host-1"))).scalar_one()
    assert {e.tenant_id for e in stored} == {node.tenant_id}, "stored under the node's own tenant"


@pytest.mark.asyncio
async def test_the_stored_rows_are_what_the_fim_pages_return(client, db_session):
    key = await _enroll(client, "fim-host-2")
    entries = [{"name": "passwd_changes", "unixTime": 1793880000, "columns": _row(target_path="/etc/shadow", action="UPDATED")}]
    with patch("app.api.v1.endpoints.log.forward_events", new=AsyncMock()):
        await client.post("/api/v1/osquery/log", json={"node_key": key, "log_type": "result", "data": json.dumps(entries)})
    node = (await db_session.execute(select(OsqueryNode).where(OsqueryNode.host_identifier == "fim-host-2"))).scalar_one()
    r = await client.get("/api/v1/osquery/fim/events", params={"tenant_id": node.tenant_id}, headers=AUTH)
    assert r.status_code == 200
    assert [i["target_path"] for i in r.json()["items"]] == ["/etc/shadow"]


@pytest.mark.asyncio
async def test_a_batch_with_no_file_rows_stores_nothing_and_a_storage_failure_does_not_stop_forwarding(client, db_session):
    key = await _enroll(client, "fim-host-3")
    other = [{"name": "logged_in_users", "unixTime": 1793880000, "columns": {"user": "root"}}]
    with patch("app.api.v1.endpoints.log.forward_events", new=AsyncMock()):
        await client.post("/api/v1/osquery/log", json={"node_key": key, "log_type": "result", "data": json.dumps(other)})
    assert (await db_session.execute(select(FimEvent))).scalars().all() == []

    files = [{"name": "passwd_changes", "unixTime": 1793880000, "columns": _row()}]
    with patch("app.api.v1.endpoints.log.forward_events", new=AsyncMock()) as fwd, patch("app.api.v1.endpoints.log.fim_event_from", side_effect=lambda *a, **k: FimEvent(tenant_id="t", node_key="k", target_path=None, action="X", event_time=NOW)):
        r = await client.post("/api/v1/osquery/log", json={"node_key": key, "log_type": "result", "data": json.dumps(files)})
    assert r.status_code == 200 and r.json() == {"node_invalid": False}
    fwd.assert_awaited_once()
