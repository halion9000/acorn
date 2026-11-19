"""Which alerts are pushed and how many messages (pure)."""

import json
from datetime import UTC, datetime, timedelta

from app.services import push_notify as pn

NOW = datetime(2026, 11, 18, tzinfo=UTC)


def row(sev, minutes, title="t", client="Acme"):
    return {"severity": sev, "created_at": NOW + timedelta(minutes=minutes), "title": title, "client": client}


def test_only_critical_alerts_after_the_last_look_are_new_oldest_first_and_the_newest_is_remembered():
    fresh, upto = pn.new_critical([row("critical", 5, "b"), row("high", 6), row("critical", 2, "a"), row("critical", -1, "old"), row("CRITICAL", 9, "c")], NOW)
    assert [r["title"] for r in fresh] == ["a", "b", "c"]
    assert upto == NOW + timedelta(minutes=9)
    assert pn.new_critical([row("low", 3)], NOW) == ([], None)


def test_at_most_ten_alerts_are_pushed_one_by_one_and_the_rest_are_counted_in_one_more_message():
    msgs = pn.messages_for([row("critical", i, f"a{i}") for i in range(13)])
    assert len(msgs) == 11
    last = json.loads(msgs[-1])
    assert "3 more critical alerts" in last["body"]
    assert json.loads(msgs[0])["title"] == "Critical alert: Acme"
    assert len(pn.messages_for([row("critical", 1)])) == 1
