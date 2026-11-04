"""Assigning many alerts at once (A114): who can be assigned, what is written, and what is left alone. Same harness as the bulk close tests, with the users table added."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alerts as ep
from app.db.database import Base
from app.models.alert import Alert
from app.models.tenant import Tenant, User
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_alerts_client_rollup import alert, tenant


@contextlib.asynccontextmanager
async def no_scope(_db, _tenant_id):
    yield


@pytest.fixture(autouse=True)
def plain(monkeypatch):
    monkeypatch.setattr(ep, "acting_as_tenant", no_scope)


@pytest.fixture
def audit(monkeypatch):
    events: list[dict] = []

    async def fake(**kw):
        events.append(kw)

    monkeypatch.setattr(ep, "emit_audit", fake)
    return events


def run(fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, Alert.__table__, User.__table__]))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def person(t, name, active=True):
    return User(id=uuid.uuid4(), tenant_id=t.id, email=f"{name}@example.com", account_name=name, username=name, hashed_password="x", role="soc_analyst", is_active=active)


async def seed(s):
    parent, other = tenant("Live Oak"), tenant("Unrelated")
    a = tenant("Setpoint", parent.id)
    s.add_all([parent, a, other])
    await s.flush()
    amy, off, stranger = person(parent, "amy"), person(parent, "off", active=False), person(other, "eve")
    s.add_all([amy, off, stranger, alert(parent, "own"), alert(a, "client-alert"), alert(other, "secret")])
    await s.commit()
    return parent, a, other, amy, off, stranger


def assign(s, caller, ids, assignee, **over):
    body = ep.BulkAssignRequest(alert_ids=ids, assignee_id=assignee, **over)
    return ep.bulk_assign_alerts(body, SimpleNamespace(headers={}, client=None), SimpleNamespace(tenant_id=caller, user_id=uuid.uuid4()), s)


async def alerts(s):
    return {x.title: x for x in (await s.execute(select(Alert))).scalars().all()}


def test_the_organizations_and_its_clients_alerts_go_to_the_person_with_the_note_in_the_audit_log(audit):
    async def go(s):
        parent, a, other, amy, *_ = await seed(s)
        rows = await alerts(s)
        ids = [rows["own"].id, rows["client-alert"].id]
        out = await assign(s, parent.id, ids, amy.id, note="  on call   this week ")
        assert (out.assigned, out.already_finished, out.not_found, out.assignee_name) == (2, 0, 0, "amy@example.com")
        after = await alerts(s)
        assert after["own"].assigned_to_id == amy.id and after["client-alert"].assigned_to_id == amy.id
        assert after["own"].assigned_at is not None and after["own"].first_seen_at is not None
        assert [(e["action"], e["changes"]["assignee_to"], e["changes"]["note"]) for e in audit] == [("alerts:bulk_assign", str(amy.id), "on call this week")] * 2
        assert {e["tenant_id"] for e in audit} == {parent.id, a.id}, "each is audited under the tenant that holds it"

    run(go)


def test_no_assignee_unassigns_and_remembers_who_it_was_taken_from(audit):
    async def go(s):
        parent, a, other, amy, *_ = await seed(s)
        rows = await alerts(s)
        await assign(s, parent.id, [rows["own"].id], amy.id)
        audit.clear()
        out = await assign(s, parent.id, [rows["own"].id], None)
        assert out.assigned == 1 and out.assignee_id is None and out.assignee_name is None
        after = await alerts(s)
        assert after["own"].assigned_to_id is None and after["own"].assigned_at is None
        assert audit[0]["changes"]["assignee_from"] == str(amy.id) and audit[0]["changes"]["assignee_to"] is None

    run(go)


def test_a_person_from_another_workspace_or_switched_off_or_unknown_cannot_be_assigned_and_nothing_changes(audit):
    async def go(s):
        parent, a, other, amy, off, stranger = await seed(s)
        rows = await alerts(s)
        for who in (stranger.id, off.id, uuid.uuid4()):
            with pytest.raises(HTTPException) as e:
                await assign(s, parent.id, [rows["own"].id], who)
            assert e.value.status_code == 404
        assert (await alerts(s))["own"].assigned_to_id is None and audit == []

    run(go)


def test_a_finished_alert_is_left_alone_and_one_the_caller_cannot_see_is_not_found(audit):
    async def go(s):
        parent, a, other, amy, *_ = await seed(s)
        rows = await alerts(s)
        rows["own"].status = "closed"
        await s.commit()
        out = await assign(s, parent.id, [rows["own"].id, rows["client-alert"].id, rows["secret"].id], amy.id)
        assert (out.assigned, out.already_finished, out.not_found) == (1, 1, 1)
        after = await alerts(s)
        assert after["own"].assigned_to_id is None and after["secret"].assigned_to_id is None and after["client-alert"].assigned_to_id == amy.id

    run(go)


def test_the_request_is_bounded_and_the_route_needs_alerts_write():
    with pytest.raises(ValidationError):
        ep.BulkAssignRequest(alert_ids=[], assignee_id=None)
    with pytest.raises(ValidationError):
        ep.BulkAssignRequest(alert_ids=[uuid.uuid4()] * 201, assignee_id=None)
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("POST", "/alerts/bulk-assign")])) == {"alerts:write"}
