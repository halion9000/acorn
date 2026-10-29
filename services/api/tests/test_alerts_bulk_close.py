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
