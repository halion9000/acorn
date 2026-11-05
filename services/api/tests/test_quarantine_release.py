"""Releasing a quarantined message from an alert: which alerts qualify, that only a confirmed, permitted request queues anything, one at a time and never twice, what is asked of CORE, and the link a ticket carries."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from app.api.v1.endpoints import alert_quarantine_release as ep
from app.services import alert_ticket_rules as tr
from app.services import quarantine_release as qr
from fastapi import HTTPException

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
TENANT = uuid.uuid4()


def raw(**over):
    base = {
        "source": "cipp",
        "finding": {"uid": "quarantine-release:t1:Identity-1", "title": "x"},
        "unmapped": {
            "context": {
                "cipp_tenant_id": "t1-guid",
                "quarantine_identity": "tenant\\guid-1\\guid-2",
                "username": "kim@acme.com",
                "sender": "ceo@lookalike.example",
                "quarantine_type": "HighConfPhish",
            }
        },
    }
    base.update(over)
    return base


def test_a_release_alert_says_which_message_for_whom_from_whom_and_why_it_was_held():
    assert qr.quarantine_of(raw()) == {
        "identity": "tenant\\guid-1\\guid-2",
        "client": "t1-guid",
        "recipient": "kim@acme.com",
        "sender": "ceo@lookalike.example",
        "kind": "HighConfPhish",
    }


def test_any_other_alert_or_one_missing_the_message_or_its_client_cannot_be_released_from_here():
    assert qr.quarantine_of(raw(finding={"uid": "phish-report:t1:x"})) is None
    assert qr.quarantine_of(raw(finding={})) is None
    assert qr.quarantine_of({"source": "cipp"}) is None
    for key in ("quarantine_identity", "cipp_tenant_id"):
        ctx = dict(raw()["unmapped"]["context"])
        ctx.pop(key)
        assert qr.quarantine_of(raw(unmapped={"context": ctx})) is None, key
    assert qr.quarantine_of(None) is None and qr.quarantine_of("text") is None


def test_the_ticket_link_is_https_only_and_needs_the_consoles_address():
    aid = uuid.uuid4()
    assert qr.release_link("https://acorn.example.com/", aid) == f"https://acorn.example.com/alerts/{aid}?release=1"
    for bad in ("", "   ", "http://acorn.example.com", "javascript:alert(1)", "https://bad host.example"):
        assert qr.release_link(bad, aid) is None, bad


def test_a_ticket_for_a_quarantine_alert_carries_the_link_and_any_other_ticket_does_not(monkeypatch):
    monkeypatch.setattr(tr.settings, "CONSOLE_PUBLIC_BASE_URL", "https://acorn.example.com")
    a = NS(id=uuid.uuid4(), title="t", description="d", raw_event=raw())
    assert tr._release_url(a) == f"https://acorn.example.com/alerts/{a.id}?release=1"
    p = tr.ticket_params(a, "77", "t", tr._release_url(a))
    assert f"/alerts/{a.id}?release=1" in p["details"] and "you will be asked to confirm" in p["details"]
    other = NS(id=uuid.uuid4(), title="t", description="d", raw_event={"source": "huntress"})
    assert tr._release_url(other) is None and "release" not in tr.ticket_params(other, None, "t", tr._release_url(other))["details"]
    monkeypatch.setattr(tr.settings, "CONSOLE_PUBLIC_BASE_URL", "")
    assert tr._release_url(a) is None, "no public address, no link; the ticket is still made"
    long = tr.ticket_params(
        NS(id=uuid.uuid4(), title="t", description="x" * 9000), None, "t", "https://acorn.example.com/alerts/1?release=1"
    )
    assert len(long["details"]) <= tr.DETAILS_MAX and long["details"].endswith(
        "?release=1"
    ), "the link is never cut off by a long description"


def row(status, minutes_ago=1, message=None):
    return NS(status=status, created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago), result_message=message)


def test_where_a_release_stands_is_read_from_the_actions_newest_first():
    now = datetime.now(UTC)
    assert ep.state_of([], now)[0] == "none"
    assert ep.state_of([row("pending")], now)[0] == "pending"
    assert ep.state_of([row("claimed")], now)[0] == "claimed"
    assert (
        ep.state_of([row("failed", 1, "CIPP refused"), row("done", 50)], now)[0] == "done"
    ), "a release that worked wins over a later failed try"
    assert ep.state_of([row("failed", 1, "CIPP refused")], now)[:2] == ("failed", "CIPP refused")
    assert ep.state_of([row("pending", 45)], now)[0] == "failed", "a request nobody collected for too long is not still waiting"


class Rows:
    def __init__(self, items=()):
        self.items = list(items)

    def scalar_one_or_none(self):
        return self.items[0] if self.items else None

    def scalars(self):
        return self

    def all(self):
        return self.items


class FakeDB:
    def __init__(self, *results):
        self.results, self.added, self.commits = list(results), [], 0

    async def execute(self, _stmt):
        return self.results.pop(0) if self.results else Rows()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


@pytest.fixture
def wired(monkeypatch):
    audits = []

    @contextlib.asynccontextmanager
    async def scope(_db, _own, _alert_id):
        yield TENANT

    async def fake_audit(**kw):
        audits.append(kw)

    monkeypatch.setattr(ep, "alert_scope", scope)
    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    return audits


def user():
    return NS(tenant_id=TENANT, user_id=uuid.uuid4(), email="hal@goliveoak.com")


def release(db, confirm=True):
    return asyncio.run(ep.release_quarantine(uuid.uuid4(), ep.ReleaseRequest(confirm=confirm), MagicMock(), user(), db))


def alert(**over):
    return NS(id=uuid.uuid4(), raw_event=raw(**over))


def test_a_confirmed_request_queues_one_release_for_core_naming_the_message_and_audits_who_asked(wired):
    db = FakeDB(Rows([alert()]), Rows([]))
    out = release(db)
    (queued,) = db.added
    assert (queued.vendor, queued.action, queued.status, queued.tenant_id) == ("core", "release_quarantine", "pending", TENANT)
    assert queued.params == {
        "client_id": "t1-guid",
        "quarantine_identity": "tenant\\guid-1\\guid-2",
        "recipient": "kim@acme.com",
        "requested_by_name": "hal@goliveoak.com",
    }
    assert out.state == "pending" and out.recipient == "kim@acme.com" and db.commits == 1
    assert wired[0]["action"] == "alerts:quarantine_release_requested" and wired[0]["changes"]["sender"] == "ceo@lookalike.example"


def test_without_confirmation_nothing_is_queued(wired):
    db = FakeDB(Rows([alert()]), Rows([]))
    with pytest.raises(HTTPException) as e:
        release(db, confirm=False)
    assert e.value.status_code == 422 and db.added == [] and db.commits == 0


def test_an_unknown_alert_a_non_release_alert_a_waiting_request_and_an_already_released_message_are_all_refused(wired):
    cases = [
        (FakeDB(Rows([])), 404),
        (FakeDB(Rows([alert(finding={"uid": "defender:t:1"})])), 422),
        (FakeDB(Rows([alert()]), Rows([row("pending")])), 409),
        (FakeDB(Rows([alert()]), Rows([row("done", 5)])), 409),
    ]
    for db, code in cases:
        with pytest.raises(HTTPException) as e:
            release(db)
        assert e.value.status_code == code
        assert db.added == [] and db.commits == 0 and wired == []


def test_after_a_failed_try_it_can_be_asked_for_again(wired):
    db = FakeDB(Rows([alert()]), Rows([row("failed", 5, "CIPP refused")]))
    assert release(db).state == "pending" and len(db.added) == 1


def test_the_info_says_whether_this_alert_can_be_released_and_where_it_stands(wired):
    plain = asyncio.run(ep.quarantine_info(uuid.uuid4(), user(), FakeDB(Rows([alert(finding={})]))))
    assert plain.available is False
    done = asyncio.run(ep.quarantine_info(uuid.uuid4(), user(), FakeDB(Rows([alert()]), Rows([row("done", 3, "Released")]))))
    assert (done.available, done.state, done.message, done.recipient) == (True, "done", "Released", "kim@acme.com")
    with pytest.raises(HTTPException) as e:
        asyncio.run(ep.quarantine_info(uuid.uuid4(), user(), FakeDB(Rows([]))))
    assert e.value.status_code == 404


def test_the_routes_need_the_right_permissions():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("POST", "/alerts/{alert_id}/release-quarantine")])) == {"identities:respond"}
    assert set(required_permissions(found[("GET", "/alerts/{alert_id}/quarantine")])) == {"alerts:read"}


def test_a_finished_release_is_noted_on_the_alert_without_losing_what_was_there():
    a = NS(enrichment_data={"keep": 1})
    db = FakeDB(Rows([a]))
    assert asyncio.run(qr.note_quarantine_released(db, TENANT, uuid.uuid4(), NOW)) is True
    assert a.enrichment_data == {"keep": 1, "quarantine_release": {"released_at": NOW.isoformat()}}
    assert asyncio.run(qr.note_quarantine_released(FakeDB(Rows([])), TENANT, uuid.uuid4(), NOW)) is False
