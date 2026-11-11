"""Automatic installs, the routes: what a rule stores and what is refused before anything is saved."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import tool_deploy_rules as ep
from fastapi import HTTPException
from pydantic import ValidationError

OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()
SCRIPTS = {
    201: NS(id=201, name="Install Huntress (Windows)", one_click=False),
    202: NS(id=202, name="Install Huntress (Mac)", one_click=True),
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
    audits = []

    async def fake_audit(**kw):
        audits.append(kw)

    monkeypatch.setattr(ep, "emit_audit", fake_audit)
    monkeypatch.setattr(ep, "published", AsyncMock(return_value=SCRIPTS))
    monkeypatch.setattr(ep, "_scope", AsyncMock(return_value=([CLIENT], {CLIENT: "Acme"})))
    return audits


def user():
    return NS(tenant_id=OWNER, user_id=uuid.uuid4())


def body(**over):
    return ep.DeployRuleIn(**{"tool": "huntress", "scope": "all", "windows_script_id": 201, "mac_script_id": 202, **over})


def run(b, db):
    return asyncio.run(ep.make_deploy_rule(b, MagicMock(), user(), db))


def test_a_rule_stores_the_tool_place_and_scripts_and_audits(wired):
    db = FakeDB(Rows([]), Rows([]))
    out = run(body(), db)
    (stored,) = db.added
    assert (stored.tool, stored.scope, stored.client_tenant_id, stored.windows_script_id, stored.mac_script_id, stored.tenant_id) == (
        "huntress",
        "all",
        None,
        201,
        202,
        OWNER,
    )
    assert (out.tool_name, out.windows_script, out.mac_script, out.active) == ("Huntress", SCRIPTS[201].name, SCRIPTS[202].name, True)
    assert db.commits == 1 and wired[0]["action"] == "tool_deploy_rule:created" and wired[0]["changes"]["tool"] == "huntress"


def test_a_client_rule_is_tied_to_that_client_and_one_script_is_enough(wired):
    db = FakeDB(Rows([]), Rows([]))
    run(body(scope="client", client_id=CLIENT, mac_script_id=None), db)
    assert db.added[0].client_tenant_id == CLIENT and db.added[0].mac_script_id is None


def test_refusals_save_nothing(wired):
    for b, db, code in (
        (body(windows_script_id=None, mac_script_id=None), FakeDB(), 422),
        (body(scope="client"), FakeDB(), 422),
        (body(windows_script_id=999), FakeDB(), 422),
        (body(scope="client", client_id=OWNER), FakeDB(), 422),
        (body(), FakeDB(Rows([(i,) for i in range(ep.MAX_RULES)])), 409),
        (body(), FakeDB(Rows([]), Rows([NS(id=1)])), 409),
    ):
        with pytest.raises(HTTPException) as e:
            run(b, db)
        assert e.value.status_code == code and db.added == [] and db.commits == 0


def test_a_tool_that_is_not_one_of_the_three_is_refused_by_the_request_model():
    for bad in ({"tool": "ninjaone"}, {"tool": "evil"}, {"windows_script_id": 0}):
        with pytest.raises(ValidationError):
            body(**bad)


def test_turning_a_rule_off_sets_the_time_audits_it_and_refuses_a_missing_or_already_off_one(wired):
    rule = NS(
        id=uuid.uuid4(),
        tool="huntress",
        scope="all",
        client_tenant_id=None,
        windows_script_id=201,
        mac_script_id=None,
        via_addigy=False,
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    db = FakeDB(Rows([rule]))
    out = asyncio.run(ep.turn_off_deploy_rule(rule.id, MagicMock(), user(), db))
    assert rule.revoked_at is not None and out.active is False and wired[0]["action"] == "tool_deploy_rule:turned_off"
    for found in (Rows([]), Rows([rule])):
        with pytest.raises(HTTPException) as e:
            asyncio.run(ep.turn_off_deploy_rule(rule.id, MagicMock(), user(), FakeDB(found)))
        assert e.value.status_code == 404


def test_a_rule_can_be_addigy_only_but_only_for_huntress(wired):
    db = FakeDB(Rows([]), Rows([]))
    out = run(body(windows_script_id=None, mac_script_id=None, via_addigy=True), db)
    assert db.added[0].via_addigy is True and out.via_addigy is True and wired[0]["changes"]["via_addigy"] is True
    for b in (
        body(tool="fieldeffect", via_addigy=True, windows_script_id=None, mac_script_id=None),
        body(tool="screenconnect", via_addigy=True),
    ):
        with pytest.raises(HTTPException) as e:
            run(b, FakeDB())
        assert e.value.status_code == 422
