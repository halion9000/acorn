"""Script rules, the routes: what a rule stores, that the alert it was made from is run now, and what is refused before anything is saved."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pytest
from app.api.v1.endpoints import alert_script_rules as ep
from fastapi import HTTPException
from pydantic import ValidationError

OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()
TITLE = "ScreenConnect for another server (514f) found on SOMEHOST"
SCRIPTS = {
    101: NS(id=101, name="Remove rogue ScreenConnect (Windows)", one_click=False),
    102: NS(id=102, name="Remove rogue ScreenConnect (Mac)", one_click=True),
}


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

    async def fake_queue(_db, rule, scripts, now, source_alert_id=None):
        queued.append((rule, source_alert_id))
        return 2

    async def fake_published(_db, _owner):
        return SCRIPTS

    monkeypatch.setattr(ep, "alert_scope", scope)
    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    monkeypatch.setattr(ep, "queue_for_rule", fake_queue)
    monkeypatch.setattr(ep, "published", fake_published)
    return audits, queued


def user():
    return NS(tenant_id=OWNER, user_id=uuid.uuid4())


def alert():
    return NS(rule_id=None, rule_name=None, title=TITLE, raw_event={"source": "aisoc-remote-tools"}, connector_type=None)


def body(**over):
    return ep.ScriptRuleIn(**{"alert_id": uuid.uuid4(), "scope": "client", "windows_script_id": 101, "mac_script_id": 102, **over})


def test_a_rule_stores_the_type_the_scripts_and_the_required_tool_runs_the_source_alert_now_and_audits(wired):
    audits, queued = wired
    db = FakeDB(Rows([alert()]), Rows([]), Rows([]))
    b = body(requires_tool="screenconnect")
    out = asyncio.run(ep.make_script_rule(b, MagicMock(), user(), db))
    (stored,) = db.added
    assert (stored.signature, stored.source, stored.scope, stored.client_tenant_id, stored.tenant_id) == (
        f"title:{TITLE}",
        "aisoc-remote-tools",
        "client",
        CLIENT,
        OWNER,
    )
    assert (stored.windows_script_id, stored.mac_script_id, stored.requires_tool) == (101, 102, "screenconnect")
    assert queued == [(stored, b.alert_id)]
    assert (out.queued_now, out.windows_script, out.mac_script, out.active) == (2, SCRIPTS[101].name, SCRIPTS[102].name, True)
    assert (
        db.commits == 1 and audits[0]["action"] == "alert_script_rule:created" and audits[0]["changes"]["requires_tool"] == "screenconnect"
    )


def test_one_script_is_enough_and_a_rule_for_all_clients_is_not_tied_to_the_alerts_client(wired):
    db = FakeDB(Rows([alert()]), Rows([]), Rows([]))
    asyncio.run(ep.make_script_rule(body(scope="all", mac_script_id=None), MagicMock(), user(), db))
    assert db.added[0].client_tenant_id is None and db.added[0].mac_script_id is None and db.added[0].windows_script_id == 101


def test_no_script_a_script_cord_has_not_switched_on_an_unknown_alert_a_duplicate_and_too_many_are_refused_and_nothing_is_saved(wired):
    for db, b, code in (
        (FakeDB(), body(windows_script_id=None, mac_script_id=None), 422),
        (FakeDB(), body(windows_script_id=999), 422),
        (FakeDB(Rows([])), body(), 404),
        (FakeDB(Rows([alert()]), Rows([]), Rows([NS(id=1)])), body(), 409),
        (FakeDB(Rows([alert()]), Rows([(i,) for i in range(ep.MAX_RULES)])), body(), 409),
    ):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ep.make_script_rule(b, MagicMock(), user(), db))
        assert e.value.status_code == code and db.added == [] and db.commits == 0


def test_a_tool_that_is_not_in_the_list_is_refused_by_the_request_model():
    with pytest.raises(ValidationError):
        body(requires_tool="evilcorp")
    with pytest.raises(ValidationError):
        body(windows_script_id=0)


def test_turning_a_rule_off_sets_the_time_audits_it_and_refuses_a_missing_or_already_off_one(wired):
    audits, _ = wired
    rule = NS(
        id=uuid.uuid4(),
        scope="client",
        client_tenant_id=CLIENT,
        source=None,
        title="t",
        windows_script_id=101,
        mac_script_id=None,
        requires_tool=None,
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    db = FakeDB(Rows([rule]))
    out = asyncio.run(ep.turn_off_script_rule(rule.id, MagicMock(), user(), db))
    assert rule.revoked_at is not None and out.active is False and db.commits == 1
    assert audits[0]["action"] == "alert_script_rule:turned_off"
    for found in (Rows([]), Rows([rule])):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ep.turn_off_script_rule(rule.id, MagicMock(), user(), FakeDB(found)))
        assert e.value.status_code == 404
