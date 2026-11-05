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


def alert(enrichment=None, **over):
    return NS(id=uuid.uuid4(), raw_event=raw(**over), enrichment_data=enrichment or {})


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


def open_alert(status="new", enrichment=None):
    return NS(
        id=uuid.uuid4(),
        status=status,
        resolved_at=None,
        updated_at=None,
        enrichment_data=enrichment if enrichment is not None else {"keep": 1},
    )


def noted(a, **kw):
    db = FakeDB(Rows([a]))
    return asyncio.run(qr.note_quarantine_released(db, TENANT, a.id, NOW, **kw)), db


def test_a_release_from_here_is_recorded_with_who_closes_an_open_alert_and_asks_core_to_note_the_tickets():
    a = open_alert(
        "in_progress", {"keep": 1, "tickets": [{"system": "halopsa", "id": "555"}], "manual_tickets": [{"id": "556"}, {"id": "555"}]}
    )
    done, db = noted(a, by="hal@goliveoak.com")
    assert done is True
    assert (
        a.enrichment_data["quarantine_release"] == {"released_at": NOW.isoformat(), "by": "hal@goliveoak.com"}
        and a.enrichment_data["keep"] == 1
    )
    assert (a.status, a.resolved_at) == ("resolved", NOW), "an analyst who released it has decided: the alert is closed whatever it was"
    (note,) = db.added
    assert (note.vendor, note.action, note.status, note.alert_id) == ("core", "ticket_note", "pending", a.id)
    assert note.params["ticket_ids"] == ["555", "556"]
    assert "released from A.C.O.R.N by hal@goliveoak.com at 2026-11-05 12:00 UTC" in note.params["note"]


def test_a_release_seen_elsewhere_is_credited_to_someone_else_and_leaves_an_analysts_open_alert_alone():
    working = open_alert("investigating", {"tickets": [{"id": "9"}]})
    done, db = noted(working, by=qr.ELSEWHERE, resolve_any_open=False)
    assert done is True and working.status == "investigating", "somebody else released it; the analyst's own work is not closed under them"
    assert working.enrichment_data["quarantine_release"]["by"] == "someone else"
    assert "released by someone else" in db.added[0].params["note"] and "Nothing more to release" in db.added[0].params["note"]
    fresh = open_alert("new", {})
    noted(fresh, by=qr.ELSEWHERE, resolve_any_open=False)
    assert fresh.status == "resolved"


def test_an_alert_with_no_ticket_gets_no_note_and_a_finished_alert_is_not_reopened_or_changed():
    a = open_alert("new", {})
    done, db = noted(a)
    assert done is True and db.added == []
    finished = open_alert("closed", {})
    noted(finished)
    assert finished.status == "closed" and finished.resolved_at is None


def test_it_is_recorded_once_so_a_second_report_changes_nothing_and_queues_nothing():
    a = open_alert("new", {"tickets": [{"id": "5"}]})
    first, _ = noted(a)
    second, db = noted(a)
    assert (first, second) == (True, False) and db.added == []
    assert asyncio.run(qr.note_quarantine_released(FakeDB(Rows([])), TENANT, uuid.uuid4(), NOW)) is False


def test_halo_ticket_numbers_come_from_both_kinds_of_link_once_each_and_ignore_other_systems_and_junk():
    e = {
        "tickets": [{"system": "halopsa", "id": 5}, {"system": "jira", "id": "J-1"}, "x"],
        "manual_tickets": [{"id": "5"}, {"id": " 7 "}, {"id": ""}],
    }
    assert qr.halo_ticket_ids(e) == ["5", "7"]
    assert qr.halo_ticket_ids(None) == [] and qr.halo_ticket_ids({"tickets": "no"}) == []


def test_an_alert_that_records_a_release_reads_as_done_in_words_that_say_who_and_cannot_be_released_again(wired):
    e = {"quarantine_release": {"released_at": "2026-11-05T12:00:00+00:00", "by": "someone else"}}
    info = asyncio.run(ep.quarantine_info(uuid.uuid4(), user(), FakeDB(Rows([alert(enrichment=e)]), Rows([]))))
    assert info.state == "done" and info.message == "Already released by someone else in Microsoft 365 (2026-11-05 12:00 UTC)."
    mine = {"quarantine_release": {"released_at": "2026-11-05T12:00:00+00:00", "by": "hal@goliveoak.com"}}
    assert "Released from A.C.O.R.N by hal@goliveoak.com" in ep.released_record(mine, "none", None, None)[1]
    assert ep.released_record({}, "failed", "x", None) == ("failed", "x", None), "no record, nothing changes"
    db = FakeDB(Rows([alert(enrichment=e)]), Rows([]))
    with pytest.raises(HTTPException) as err:
        release(db)
    assert err.value.status_code == 409 and db.added == [], "a message someone else already released is not released again"


def test_a_closure_for_a_cipp_alert_may_name_any_of_its_four_kinds_of_record_and_other_vendors_keep_their_own_prefix():
    from app.api.v1.endpoints.inbox_core_feed import closed_prefixes

    for uid in ("quarantine-release:t:1", "defender:t:2", "entra-risk:t:3", "phish-report:t:4", "cipp:5", "cipp-escalation:6"):
        assert uid.startswith(closed_prefixes("cipp")), uid
    assert not "huntress:1".startswith(closed_prefixes("cipp"))
    assert closed_prefixes("huntress") == ("huntress:", "huntress-")
    assert not "defender:t:1".startswith(closed_prefixes("huntress"))


def test_core_can_say_the_message_was_already_released_and_that_credits_someone_else_not_the_person_who_asked():
    from app.api.v1.endpoints.inbox_core_feed import ActionResult

    assert ActionResult(status="done", already_released=True).already_released is True
    assert ActionResult(status="done").already_released is False, "an ordinary answer is not an 'already released' one"
    a = open_alert("new", {})
    asked_by_hal, _ = noted(a, by="hal@goliveoak.com")
    assert asked_by_hal is True and a.enrichment_data["quarantine_release"]["by"] == "hal@goliveoak.com"
    b = open_alert("new", {})
    noted(b, by=qr.ELSEWHERE)
    assert b.enrichment_data["quarantine_release"]["by"] == "someone else"


def check_row(status, minutes_ago=1, message=None):
    return row(status, minutes_ago, message)


def test_the_look_into_why_it_was_held_follows_the_newest_request():
    now = datetime.now(UTC)
    assert ep.check_state_of([], now) == ("none", None, None)
    assert ep.check_state_of([check_row("pending")], now)[:2] == ("pending", None)
    assert ep.check_state_of([check_row("claimed")], now)[:2] == ("claimed", None)
    text = "Looks malicious or fake: do not release it.\n[BAD] Sender checks: SPF fail"
    assert ep.check_state_of([check_row("done", 2, text), check_row("failed", 9, "old")], now)[:2] == ("done", text), "the newest wins"
    assert ep.check_state_of(
        [check_row("failed", 2, "Microsoft 365 does not list this message any more."), check_row("done", 9, "old")], now
    )[:2] == ("failed", "Microsoft 365 does not list this message any more.")
    assert ep.check_state_of([check_row("pending", 45)], now)[0] == "failed", "a request nobody collected for too long is not still waiting"


def check(db):
    return asyncio.run(ep.check_quarantine(uuid.uuid4(), MagicMock(), user(), db))


def test_asking_for_the_check_queues_one_read_only_request_for_core_and_audits_it(wired):
    db = FakeDB(Rows([alert()]), Rows([]))
    out = check(db)
    (queued,) = db.added
    assert (queued.vendor, queued.action, queued.status, queued.tenant_id) == ("core", "quarantine_check", "pending", TENANT)
    assert queued.params == {
        "client_id": "t1-guid",
        "quarantine_identity": "tenant\\guid-1\\guid-2",
    }, "only which message and which client: nothing that could release it"
    assert out.check_state == "pending" and db.commits == 1
    assert wired[0]["action"] == "alerts:quarantine_check_requested"


def test_the_check_is_refused_for_an_unknown_alert_a_non_release_alert_or_one_already_waiting_and_can_be_asked_again_after_a_finished_one(
    wired,
):
    for db, code in (
        (FakeDB(Rows([])), 404),
        (FakeDB(Rows([alert(finding={"uid": "defender:t:1"})])), 422),
        (FakeDB(Rows([alert()]), Rows([row("pending")])), 409),
    ):
        with pytest.raises(HTTPException) as e:
            check(db)
        assert e.value.status_code == code and db.added == []
    again = FakeDB(Rows([alert()]), Rows([row("done", 5, "Looks like a false positive")]))
    assert check(again).check_state == "pending" and len(again.added) == 1


def test_the_info_carries_what_the_check_found(wired):
    found = row("done", 3, "Looks malicious or fake: do not release it.")
    info = asyncio.run(ep.quarantine_info(uuid.uuid4(), user(), FakeDB(Rows([alert()]), Rows([]), Rows([found]))))
    assert (info.check_state, info.check_text) == ("done", "Looks malicious or fake: do not release it.")
    assert info.state == "none", "looking is not releasing: the release state is untouched"


def test_the_check_route_needs_identities_respond():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("POST", "/alerts/{alert_id}/check-quarantine")])) == {"identities:respond"}


def test_a_release_made_from_here_reads_as_released_and_only_one_made_elsewhere_reads_as_already_released():
    mine = {"quarantine_release": {"released_at": "2026-11-05T18:16:00+00:00", "by": "hal@goliveoak.com"}}
    assert ep.released_record(mine, "none", None, None)[1] == "Released from A.C.O.R.N by hal@goliveoak.com (2026-11-05 18:16 UTC)."
    anon = {"quarantine_release": {"released_at": "2026-11-05T18:16:00+00:00", "by": "A.C.O.R.N"}}
    assert ep.released_record(anon, "none", None, None)[1] == "Released from A.C.O.R.N (2026-11-05 18:16 UTC)."
    other = {"quarantine_release": {"released_at": "2026-11-05T18:16:00+00:00", "by": "someone else"}}
    assert ep.released_record(other, "none", None, None)[1] == "Already released by someone else in Microsoft 365 (2026-11-05 18:16 UTC)."
    assert "Already" not in ep.released_record(mine, "none", None, None)[1]
