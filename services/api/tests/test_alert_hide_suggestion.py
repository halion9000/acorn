"""Suggesting that an alert type be hidden once it has been closed as a false positive three times: when it suggests, when it does not, and that it only ever suggests."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_suppressions as ep
from app.services import alert_scope as scope
from app.services import alert_suppression as sup
from fastapi import HTTPException

OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()


@pytest.mark.parametrize("count,hidden,expected", [(0, False, False), (2, False, False), (3, False, True), (40, False, True), (3, True, False), (40, True, False)])
def test_it_suggests_from_three_false_positives_unless_a_rule_already_hides_the_type(count, hidden, expected):
    assert sup.should_suggest_hiding(count, hidden) is expected


class Seq:
    """A session that answers each query in turn: the alert, the false-positive count, then the number of rules already hiding the type."""

    def __init__(self, alert, counts):
        self.answers = [("one", alert), *[("count", c) for c in counts]]
        self.committed = False

    async def execute(self, statement):
        kind, value = self.answers.pop(0)
        if kind == "one":
            return SimpleNamespace(scalar_one_or_none=lambda: value)
        return SimpleNamespace(scalar_one=lambda: value)

    async def commit(self):
        self.committed = True


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    async def find(db, own, alert_id):
        return CLIENT

    monkeypatch.setattr(scope, "find_alert_tenant", find)
    monkeypatch.setattr(scope, "acting_as_tenant", lambda db, tid: contextlib.nullcontext())


def ask(alert, counts):
    db = Seq(alert, counts)
    out = asyncio.run(ep.hide_suggestion(uuid.uuid4(), SimpleNamespace(tenant_id=OWNER, user_id=uuid.uuid4()), db))
    return out, db


def an_alert():
    return SimpleNamespace(rule_id="rule-1", title="Disk almost full", raw_event={}, connector_type=None, affected_hosts=[])


def test_three_false_positives_and_no_rule_gives_a_suggestion_with_the_count():
    out, db = ask(an_alert(), [3, 0])
    assert (out.suggest, out.false_positives, out.threshold, out.days) == (True, 3, 3, 90)
    assert db.committed is False, "it suggests and changes nothing"


def test_two_do_not_and_a_rule_already_hiding_it_stops_the_suggestion():
    assert ask(an_alert(), [2, 0])[0].suggest is False
    out, _ = ask(an_alert(), [5, 1])
    assert out.suggest is False and out.false_positives == 5


def test_an_alert_the_caller_cannot_see_is_a_404():
    with pytest.raises(HTTPException) as e:
        ask(None, [])
    assert e.value.status_code == 404
