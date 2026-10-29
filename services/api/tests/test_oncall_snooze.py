"""An on-call snooze ends when its time does.

The status stayed "snoozed" until the person changed it by hand, so the paging list kept skipping someone whose snooze ended hours ago, and a filter for "available" left them out.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.v1.endpoints import oncall as ep

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def row(status, until=None, **over):
    base = {
        "user_id": uuid.uuid4(),
        "status": status,
        "until": until,
        "schedule_ref": None,
        "rotation": None,
        "note": None,
        "updated_at": NOW - timedelta(hours=1),
    }
    base.update(over)
    return SimpleNamespace(**base)


def person(name):
    return SimpleNamespace(email=f"{name}@acme.test", username=name)


class TestEffectiveStatus:
    def test_a_snooze_that_has_ended_is_available_with_no_end_time(self):
        assert ep.effective_status(row("snoozed", NOW - timedelta(minutes=1)), NOW) == ("available", None)
        assert ep.effective_status(row("snoozed", NOW), NOW) == ("available", None), "the moment it ends it is over"

    def test_a_snooze_still_running_is_snoozed_until_its_time(self):
        until = NOW + timedelta(minutes=20)
        assert ep.effective_status(row("snoozed", until), NOW) == ("snoozed", until)

    def test_a_snooze_with_no_end_time_stays_as_it_is(self):
        assert ep.effective_status(row("snoozed", None), NOW) == ("snoozed", None)

    def test_other_statuses_are_left_alone_whatever_their_time(self):
        past = NOW - timedelta(days=1)
        for status in ("available", "busy", "offline"):
            assert ep.effective_status(row(status, past), NOW) == (status, past)

    def test_a_time_with_no_zone_is_read_as_utc(self):
        naive_past = (NOW - timedelta(minutes=5)).replace(tzinfo=None)
        assert ep.effective_status(row("snoozed", naive_past), NOW)[0] == "available"


def _list(rows, status_filter=None):
    db = MagicMock()
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    db.execute = AsyncMock(return_value=result)
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    return asyncio.run(ep.list_oncall(user, db, status_filter=status_filter))


def test_the_list_shows_an_ended_snooze_as_available_and_sorts_it_there():
    rows = [
        (row("snoozed", datetime.now(UTC) - timedelta(minutes=30)), person("ended")),
        (row("snoozed", datetime.now(UTC) + timedelta(minutes=30)), person("running")),
        (row("busy"), person("busy")),
        (row("available"), person("free")),
    ]
    out = _list(rows)
    by_name = {i.user_name: i for i in out.items}
    assert by_name["ended"].status == "available" and by_name["ended"].until is None
    assert by_name["running"].status == "snoozed" and by_name["running"].until is not None
    assert [i.user_name for i in out.items][-1] == "running", "available people first, the still-snoozed after the busy"
    assert {i.user_name for i in out.items[:2]} == {"ended", "free"}


def test_the_status_filter_works_on_what_is_shown():
    ended = row("snoozed", datetime.now(UTC) - timedelta(minutes=5))
    rows = [
        (ended, person("ended")),
        (row("available"), person("free")),
        (row("snoozed", datetime.now(UTC) + timedelta(hours=1)), person("running")),
    ]
    assert {i.user_name for i in _list(rows, "available").items} == {"ended", "free"}
    assert [i.user_name for i in _list(rows, "snoozed").items] == ["running"]
    assert _list(rows, "offline").items == []
    assert _list(rows, "offline").total == 0


def test_my_own_status_also_shows_the_snooze_as_over():
    status_row = row("snoozed", datetime.now(UTC) - timedelta(minutes=10))
    db = MagicMock()
    result = MagicMock()
    result.first = MagicMock(return_value=(status_row, person("me")))
    db.execute = AsyncMock(return_value=result)
    out = asyncio.run(ep.my_oncall(SimpleNamespace(tenant_id=uuid.uuid4(), user_id=status_row.user_id, email="me@acme.test"), db))
    assert (out.status, out.until) == ("available", None)
