"""Closing many alerts at once with one reason (backlog A18): who can be closed, what is written, and what is left alone."""

import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alerts as ep
from app.models.alert import Alert
from pydantic import ValidationError
from sqlalchemy import select
from test_alerts_client_rollup import run, seed  # the same harness: an organization, two clients and an unrelated tenant, on SQLite


@pytest.fixture
def audit(monkeypatch):
    events: list[dict] = []

    async def fake(**kw):
        events.append(kw)

    monkeypatch.setattr(ep, "emit_audit", fake)
    return events


def close(s, caller, ids, **over):
    body = ep.BulkCloseRequest(alert_ids=ids, **{"reason": "duplicates of the ticket", **over})
    user = SimpleNamespace(tenant_id=caller, user_id=uuid.uuid4())
    return ep.bulk_close_alerts(body, SimpleNamespace(headers={}, client=None), user, s)


async def rows(s):
    return {a.title: a for a in (await s.execute(select(Alert))).scalars().all()}


def test_the_organization_and_its_clients_alerts_are_closed_with_the_reason_in_the_audit_log(audit):
    async def go(s):
        parent, a, b, other = await seed(s)
        before = await rows(s)
        ids = [before["own"].id, before["setpoint-new"].id, before["tecovas"].id]
        out = await close(s, parent.id, ids, reason="  duplicates   of the ticket ")
        assert (out.closed, out.already_finished, out.not_found, out.status, out.reason) == (
            3,
            0,
            0,
            "resolved",
            "duplicates of the ticket",
        )
        after = await rows(s)
        assert {t: after[t].status for t in ("own", "setpoint-new", "tecovas")} == {
            "own": "resolved",
            "setpoint-new": "resolved",
            "tecovas": "resolved",
        }
        assert all(after[t].resolved_at is not None for t in ("own", "setpoint-new", "tecovas"))
        assert after["setpoint-old"].status == "new", "an alert that was not asked for is untouched"
        assert [(e["action"], e["resource_id"], e["changes"]) for e in audit] == [
            ("alerts:bulk_close", str(i), {"status_from": "new", "status_to": "resolved", "reason": "duplicates of the ticket"})
            for i in ids
        ]
        assert {e["tenant_id"] for e in audit} == {parent.id, a.id, b.id}, "each is audited under the tenant that holds it"

    run(go)


def test_a_finished_alert_is_left_alone_and_one_the_caller_cannot_see_is_not_found(audit):
    async def go(s):
        parent, a, b, other = await seed(s)
        before = await rows(s)
        before["own"].status = "closed"
        await s.commit()
        out = await close(s, parent.id, [before["own"].id, before["secret"].id, uuid.uuid4(), before["tecovas"].id])
        assert (out.closed, out.already_finished, out.not_found) == (1, 1, 2)
        after = await rows(s)
        assert after["secret"].status == "new", "another organization's alert is never closed"
        assert after["own"].status == "closed" and after["own"].resolved_at is None, "an already finished alert is not changed"
        assert len(audit) == 1

    run(go)


def test_a_false_positive_close_sets_the_verdict_and_other_closes_do_not(audit):
    async def go(s):
        parent, *_ = await seed(s)
        before = await rows(s)
        await close(s, parent.id, [before["own"].id], status="false_positive")
        await close(s, parent.id, [before["setpoint-new"].id], status="resolved")
        after = await rows(s)
        assert (after["own"].status, after["own"].disposition) == ("false_positive", "false_positive")
        assert (after["setpoint-new"].status, after["setpoint-new"].disposition) == ("resolved", None)

    run(go)


def test_the_same_alert_twice_counts_once_and_the_request_refuses_no_reason_and_too_many_alerts(audit):
    async def go(s):
        parent, *_ = await seed(s)
        before = await rows(s)
        out = await close(s, parent.id, [before["own"].id, before["own"].id])
        assert (out.closed, len(audit)) == (1, 1)

    run(go)
    for bad in ({"reason": "no"}, {"reason": ""}, {"status": "deleted"}):
        with pytest.raises(ValidationError):
            ep.BulkCloseRequest(**{"alert_ids": [uuid.uuid4()], "reason": "fine reason", **bad})
    with pytest.raises(ValidationError):
        ep.BulkCloseRequest(alert_ids=[uuid.uuid4() for _ in range(201)], reason="fine reason")
    with pytest.raises(ValidationError):
        ep.BulkCloseRequest(alert_ids=[], reason="fine reason")


def test_a_reason_of_only_spaces_is_refused_before_anything_is_closed(audit):
    from fastapi import HTTPException

    async def go(s):
        parent, *_ = await seed(s)
        before = await rows(s)
        with pytest.raises(HTTPException) as e:
            await close(s, parent.id, [before["own"].id], reason="     ")
        assert e.value.status_code == 422
        assert (await rows(s))["own"].status == "new" and audit == []

    run(go)


# ---------------------------------------------------------------- undoing a bulk close


def undo(s, caller, items, status="resolved"):
    body = ep.BulkCloseUndoRequest(items=[ep.UndoItem(id=i, status_from=f) for i, f in items], status=status)
    user = SimpleNamespace(tenant_id=caller, user_id=uuid.uuid4())
    return ep.undo_bulk_close(body, SimpleNamespace(headers={}, client=None), user, s)


def test_the_close_says_what_it_closed_and_undoing_puts_each_alert_back_as_it_was(audit):
    async def go(s):
        parent, a, b, other = await seed(s)
        before = await rows(s)
        before["tecovas"].status = "investigating"
        await s.commit()
        ids = [before["own"].id, before["tecovas"].id]
        closed = await close(s, parent.id, ids)
        assert [(i.id, i.status_from) for i in closed.closed_items] == [(before["own"].id, "new"), (before["tecovas"].id, "investigating")]
        out = await undo(s, parent.id, [(i.id, i.status_from) for i in closed.closed_items])
        assert (out.reopened, out.changed_since, out.too_late, out.not_found) == (2, 0, 0, 0)
        s.expire_all()
        after = await rows(s)
        assert (after["own"].status, after["own"].resolved_at) == ("new", None)
        assert (after["tecovas"].status, after["tecovas"].resolved_at) == ("investigating", None)
        undone = [e for e in audit if e["action"] == "alerts:bulk_close_undone"]
        assert [(e["resource_id"], e["changes"]) for e in undone] == [
            (str(before["own"].id), {"status_from": "resolved", "status_to": "new"}),
            (str(before["tecovas"].id), {"status_from": "resolved", "status_to": "investigating"}),
        ]

    run(go)


def test_undo_leaves_alone_an_alert_changed_since_one_closed_too_long_ago_and_one_the_caller_cannot_see(audit):
    from datetime import UTC, datetime, timedelta

    async def go(s):
        parent, a, b, other = await seed(s)
        pid = parent.id  # read now: the objects are expired below
        before = await rows(s)
        closed = await close(s, pid, [before["own"].id, before["setpoint-new"].id, before["tecovas"].id])
        s.expire_all()
        now = await rows(s)
        now["own"].status = "closed"  # somebody changed it after the bulk close
        now["setpoint-new"].resolved_at = datetime.now(UTC) - timedelta(minutes=11)  # the close was more than ten minutes ago
        await s.commit()
        items = [(i.id, i.status_from) for i in closed.closed_items] + [(now["secret"].id, "new"), (uuid.uuid4(), "new")]
        out = await undo(s, pid, items)
        assert (out.reopened, out.changed_since, out.too_late, out.not_found) == (1, 1, 1, 2)
        s.expire_all()
        after = await rows(s)
        assert after["own"].status == "closed" and after["setpoint-new"].status == "resolved" and after["tecovas"].status == "new"
        assert after["secret"].status == "new", "another organization's alert is never touched"

    run(go)


def test_undoing_a_false_positive_close_takes_the_verdict_back_with_it(audit):
    async def go(s):
        parent, *_ = await seed(s)
        before = await rows(s)
        closed = await close(s, parent.id, [before["own"].id], status="false_positive")
        await undo(s, parent.id, [(i.id, i.status_from) for i in closed.closed_items], status="false_positive")
        s.expire_all()
        after = await rows(s)
        assert (after["own"].status, after["own"].disposition) == ("new", None)

    run(go)


def test_undo_cannot_be_used_to_put_an_alert_into_a_finished_status_or_to_reopen_one_it_did_not_close(audit):
    from fastapi import HTTPException

    async def go(s):
        parent, *_ = await seed(s)
        before = await rows(s)
        with pytest.raises(HTTPException) as refused:
            await undo(s, parent.id, [(before["own"].id, "closed")])
        assert refused.value.status_code == 422
        out = await undo(s, parent.id, [(before["own"].id, "investigating")])  # never closed: its status is not the one the request names
        assert (out.reopened, out.changed_since) == (0, 1)
        s.expire_all()
        assert (await rows(s))["own"].status == "new"
        assert audit == []

    run(go)
    with pytest.raises(ValidationError):
        ep.UndoItem(id=uuid.uuid4(), status_from="New; DROP")
    with pytest.raises(ValidationError):
        ep.BulkCloseUndoRequest(items=[], status="resolved")
