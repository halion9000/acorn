"""Ticket rules without a database: which alerts a rule covers, what is asked of CORE, the endpoint's refusals and audit, and the permissions."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from app.api.v1.endpoints import alert_ticket_rules as ep
from app.api.v1.endpoints.inbox_core_feed import ActionResult
from app.services import alert_ticket_rules as svc
from fastapi import HTTPException
from pydantic import ValidationError

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
CLIENT, OTHER, OWNER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
TITLE = 'A user asked to release a quarantined message: "x"'


def rule(**over):
    base = {
        "signature": f"title:{TITLE}",
        "source": "cipp",
        "scope": "client",
        "client_tenant_id": CLIENT,
        "created_at": NOW - timedelta(hours=1),
    }
    base.update(over)
    return NS(**base)


def covers(r, **over):
    args = {"tenant_id": CLIENT, "rule_id": None, "title": TITLE, "source": "cipp", "created_at": NOW}
    args.update(over)
    return svc.rule_covers(r, **args)


def test_a_new_alert_of_the_same_type_and_tool_in_the_clients_place_is_covered():
    assert covers(rule()) is True
    assert covers(rule(scope="all", client_tenant_id=None), tenant_id=OTHER) is True, "a rule for all clients covers any client"


def test_another_title_tool_or_client_is_not_covered_and_a_rule_id_makes_the_type():
    assert covers(rule(), title="Something else") is False
    assert covers(rule(), source="huntress") is False
    assert covers(rule(), tenant_id=OTHER) is False, "a client rule is for its own client"
    assert covers(rule(signature="rule:r-9"), rule_id="r-9", title="whatever the title says") is True
    assert covers(rule(signature="rule:r-9"), rule_id="r-8") is False


def test_an_alert_raised_before_the_rule_is_covered_only_as_the_alert_it_was_made_from():
    old = NOW - timedelta(days=2)
    assert covers(rule(), created_at=old) is False
    assert covers(rule(), created_at=old, source_alert_id="a1", alert_id="a1") is True
    assert covers(rule(), created_at=old, source_alert_id="a1", alert_id="a2") is False
    assert covers(rule(), created_at=None) is False
    assert covers(rule(), created_at=NOW.replace(tzinfo=None)) is True, "a time with no zone is read as UTC"


def test_an_alert_with_a_ticket_found_by_core_or_entered_by_hand_has_one_and_junk_does_not_count():
    assert svc.has_ticket({"tickets": [{"system": "halopsa", "id": "5"}]}) is True
    assert svc.has_ticket({"manual_tickets": [{"id": 7}]}) is True
    for none in (
        None,
        {},
        {"tickets": []},
        {"tickets": [{"id": ""}]},
        {"tickets": ["x", 5]},
        {"tickets": [{"system": "jira", "id": "9"}]},
        "text",
    ):
        assert svc.has_ticket(none) is False, none


def test_what_core_is_asked_carries_the_alert_title_and_details_the_halo_client_and_a_trace_of_where_it_came_from():
    alert = NS(id=uuid.uuid4(), title="  A user   asked\nto release  ", description="Details here")
    p = svc.ticket_params(alert, "77", "rule title")
    assert p["summary"] == "A user asked to release" and p["halo_client_id"] == "77"
    assert p["details"].startswith("Details here") and f"alert {alert.id}" in p["details"]
    assert "halo_client_id" not in svc.ticket_params(alert, None, "t")
    long = svc.ticket_params(NS(id=uuid.uuid4(), title="x" * 500, description="y" * 5000), None, "t")
    assert len(long["summary"]) == svc.TITLE_MAX and len(long["details"]) <= svc.DETAILS_MAX
    assert svc.ticket_params(NS(id=uuid.uuid4(), title=None, description=None), None, "From rule")["summary"] == "From rule"


def test_core_reports_the_ticket_number_as_digits_only():
    assert ActionResult(status="done", ticket_id="4521").ticket_id == "4521"
    assert ActionResult(status="failed", message="no").ticket_id is None
    for bad in ("12 34", "abc", "1" * 13, "../1"):
        with pytest.raises(ValidationError):
            ActionResult(status="done", ticket_id=bad)


class Rows:
    def __init__(self, items=()):
        self.items = list(items)

    def scalar_one_or_none(self):
        return self.items[0] if self.items else None

    def scalars(self):
        return self

    def first(self):
        return self.items[0] if self.items else None

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
    audits, queued = [], []

    @contextlib.asynccontextmanager
    async def scope(_db, _own, _alert_id):
        yield CLIENT

    async def fake_audit(**kw):
        audits.append(kw)

    async def fake_queue(_db, r, now, source_alert_id=None):
        queued.append((r, source_alert_id))
        return 1

    monkeypatch.setattr(ep, "alert_scope", scope)
    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    monkeypatch.setattr(ep, "queue_for_rule", fake_queue)
    return audits, queued


def user():
    return NS(tenant_id=OWNER, user_id=uuid.uuid4())


def make(db, scope="client"):
    alert = NS(rule_id=None, rule_name=None, title=TITLE, raw_event={"source": "cipp"}, connector_type=None)
    body = ep.TicketRuleIn(alert_id=uuid.uuid4(), scope=scope)
    return asyncio.run(ep.make_ticket_rule(body, MagicMock(), user(), db)), alert


def test_making_a_rule_from_an_alert_stores_its_type_tool_and_place_queues_the_source_alert_and_audits(wired):
    audits, queued = wired
    alert = NS(rule_id=None, rule_name=None, title=TITLE, raw_event={"source": "cipp"}, connector_type=None)
    db = FakeDB(Rows([alert]), Rows([]), Rows([]), Rows([]))
    body = ep.TicketRuleIn(alert_id=uuid.uuid4(), scope="client")
    out = asyncio.run(ep.make_ticket_rule(body, MagicMock(), user(), db))
    (stored,) = db.added
    assert (stored.signature, stored.source, stored.scope, stored.client_tenant_id, stored.tenant_id) == (
        f"title:{TITLE}",
        "cipp",
        "client",
        CLIENT,
        OWNER,
    )
    assert queued == [(stored, body.alert_id)], "the alert it was made from is asked for now"
    assert out.queued_now == 1 and out.active is True and out.scope == "client"
    assert db.commits == 1 and audits[0]["action"] == "alert_ticket_rule:created"
    assert audits[0]["changes"]["queued_now"] == 1 and audits[0]["changes"]["title"] == TITLE[:200]


def test_a_rule_for_all_clients_is_not_tied_to_the_alerts_client(wired):
    alert = NS(rule_id="r-1", rule_name=None, title="t", raw_event={}, connector_type="cipp")
    db = FakeDB(Rows([alert]), Rows([]), Rows([]), Rows([]))
    asyncio.run(ep.make_ticket_rule(ep.TicketRuleIn(alert_id=uuid.uuid4(), scope="all"), MagicMock(), user(), db))
    assert db.added[0].client_tenant_id is None and db.added[0].signature == "rule:r-1" and db.added[0].source == "cipp"


def test_a_rule_made_from_an_alert_with_a_rule_id_is_listed_under_the_types_name_not_one_devices_title(wired):
    alert = NS(rule_id="aisoc-remote-foreign", rule_name="ScreenConnect for another server", title="ScreenConnect for another server (514f25df7bb0852b) found on D68HM3L3", raw_event={"source": "aisoc-remote-tools"}, connector_type=None)
    db = FakeDB(Rows([alert]), Rows([]), Rows([]), Rows([]))
    asyncio.run(ep.make_ticket_rule(ep.TicketRuleIn(alert_id=uuid.uuid4(), scope="all"), MagicMock(), user(), db))
    assert db.added[0].title == "ScreenConnect for another server" and db.added[0].signature == "rule:aisoc-remote-foreign"
    plain = NS(rule_id=None, rule_name="ignored without a rule id", title=TITLE, raw_event={"source": "cipp"}, connector_type=None)
    db2 = FakeDB(Rows([plain]), Rows([]), Rows([]), Rows([]))
    asyncio.run(ep.make_ticket_rule(ep.TicketRuleIn(alert_id=uuid.uuid4(), scope="all"), MagicMock(), user(), db2))
    assert db2.added[0].title == TITLE[:500]


def test_an_unknown_alert_a_duplicate_rule_and_too_many_rules_are_refused_and_nothing_is_saved(wired):
    alert = NS(rule_id=None, rule_name=None, title=TITLE, raw_event={"source": "cipp"}, connector_type=None)
    body = ep.TicketRuleIn(alert_id=uuid.uuid4(), scope="client")
    for db, code in (
        (FakeDB(Rows([])), 404),
        (FakeDB(Rows([alert]), Rows([]), Rows([NS(id=1)])), 409),
        (FakeDB(Rows([alert]), Rows([(i,) for i in range(ep.MAX_RULES)])), 409),
    ):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ep.make_ticket_rule(body, MagicMock(), user(), db))
        assert e.value.status_code == code
        assert db.added == [] and db.commits == 0


def test_turning_a_rule_off_sets_the_time_and_audits_and_an_unknown_or_already_off_rule_is_404(monkeypatch):
    audits = []

    async def fake_audit(**kw):
        audits.append(kw)

    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    live = NS(
        id=uuid.uuid4(),
        tenant_id=OWNER,
        scope="client",
        client_tenant_id=CLIENT,
        source="cipp",
        title=TITLE,
        created_at=NOW,
        revoked_at=None,
    )
    db = FakeDB(Rows([live]), Rows([]))
    out = asyncio.run(ep.turn_off_ticket_rule(live.id, MagicMock(), user(), db))
    assert live.revoked_at is not None and out.active is False and db.commits == 1
    assert audits[0]["action"] == "alert_ticket_rule:turned_off"
    for found in ([], [NS(revoked_at=NOW)]):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ep.turn_off_ticket_rule(uuid.uuid4(), MagicMock(), user(), FakeDB(Rows(found))))
        assert e.value.status_code == 404


def test_the_routes_need_the_right_permissions():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("POST", "/alert-ticket-rules")])) == {"connectors:write"}
    assert set(required_permissions(found[("DELETE", "/alert-ticket-rules/{rule_id}")])) == {"connectors:write"}
    assert set(required_permissions(found[("GET", "/alert-ticket-rules")])) == {"alerts:read"}


# ---- a rule is for the alert TYPE, not for the one device or message it was made from ----


def test_type_key_ignores_the_parts_of_a_title_that_change_from_one_alert_to_the_next():
    from app.services.alert_ticket_rules import type_key

    same_quarantine = [
        'title:A user asked to release a quarantined message: "Re: Block 2027 – Updated Pricing"',
        "title:A user asked to release a quarantined message: “Invoice 88”",
        'title:A user asked to release a quarantined message: "x"',
    ]
    assert len({type_key(t) for t in same_quarantine}) == 1
    same_sc = ["title:ScreenConnect for another server (514f25df7bb0852b) found on D68HM3L3", "title:ScreenConnect for another server (344e459ab554378d) found on Mac.localdomain"]
    assert len({type_key(t) for t in same_sc}) == 1
    assert type_key(same_sc[0]) != type_key(same_quarantine[0])
    assert type_key("title:Possible initial access from an emerging threat") == "type:possible initial access from an emerging threat"
    assert type_key("rule:aisoc-remote-foreign") == "rule:aisoc-remote-foreign", "an alert with a rule id is that rule id, untouched"
    assert type_key('title:"only quoted"') == 'title:"only quoted"', "nothing left after stripping: stay exact"


def test_a_rule_made_from_one_message_or_device_covers_the_others_of_that_type_but_not_other_types():
    from app.services.alert_ticket_rules import rule_covers

    t0 = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    tenant = uuid.uuid4()
    rule = NS(signature='title:A user asked to release a quarantined message: "Re: Block 2027"', source="cipp", scope="all", client_tenant_id=None, created_at=t0)

    def covers(title, source="cipp", when=t0 + timedelta(minutes=5)):
        return rule_covers(rule, tenant_id=tenant, rule_id=None, title=title, source=source, created_at=when)

    assert covers('A user asked to release a quarantined message: "A different subject"')
    assert not covers("A user reported a phishing message")
    assert not covers('A user asked to release a quarantined message: "x"', source="huntress"), "the tool still has to match"
    assert not covers('A user asked to release a quarantined message: "x"', when=t0 - timedelta(minutes=5)), "and only alerts raised after the rule was made"
