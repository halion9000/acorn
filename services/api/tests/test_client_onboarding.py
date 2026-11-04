"""Client onboarding status: a step is done only when something is really there, and the next thing to do names the first missing step."""

import uuid

from app.api.v1.endpoints.client_onboarding import Facts, build_row, onboarding_csv

CID = uuid.uuid4()


def row(**facts):
    return build_row(CID, "Acme", Facts(**facts))


def test_a_client_with_nothing_has_no_step_done_and_is_told_to_link_its_tools_first():
    r = row()
    assert (r.done, r.total, r.percent) == (0, 5, 0)
    assert r.next_step == "Link this client's tools in Settings, Client mapping."
    assert not any(s.done for s in r.steps)


def test_each_step_is_done_only_when_its_count_is_above_zero():
    r = row(tools=2, devices=10, people=0, checks=4, checks_met=3, alerts=0)
    assert {s.key: s.done for s in r.steps} == {"tools": True, "devices": True, "people": False, "checks": True, "alerts": False}
    assert (r.done, r.percent) == (3, 60)


def test_the_next_step_is_the_first_one_missing_not_the_last():
    assert "Microsoft 365 people" in row(tools=1, devices=3).next_step
    assert "tool check" in row(tools=1, devices=3, people=5).next_step


def test_a_complete_client_has_nothing_next_and_the_details_use_the_right_words():
    r = row(tools=1, devices=1, people=1, checks=1, checks_met=0, alerts=1)
    assert (r.done, r.percent, r.next_step) == (5, 100, None)
    assert [s.detail for s in r.steps] == ["1 tool linked", "1 device", "1 person", "1 check run, 0 met", "1 alert so far"]
    many = row(tools=3, devices=12, people=40, checks=9, checks_met=7, alerts=2)
    assert [s.detail for s in many.steps] == ["3 tools linked", "12 devices", "40 people", "9 checks run, 7 met", "2 alerts so far"]


def test_the_route_needs_alerts_read():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/client-onboarding")])) == {"alerts:read"}


# ---- the route: how the five answers are put together --------------------------------------------------------------------------------------------------------

import asyncio  # noqa: E402
import contextlib  # noqa: E402
from datetime import UTC, datetime  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from app.api.v1.endpoints import client_onboarding as ep  # noqa: E402

OWNER, A, B = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def fake_db(*answers):
    """A database that answers the five queries in the order they are asked."""
    remaining = list(answers)

    async def execute(_statement):
        out = MagicMock()
        out.all.return_value = remaining.pop(0)
        return out

    return NS(execute=AsyncMock(side_effect=execute))


def test_the_clients_come_back_least_onboarded_first_with_the_earliest_data_date(monkeypatch):
    import app.api.v1.endpoints.client_onboarding as module

    monkeypatch.setattr(module, "_scope", AsyncMock(return_value=([OWNER, A, B], {A: "Zed Co", B: "Acme"})))
    monkeypatch.setattr(module, "cross_tenant_reads", lambda db: contextlib.nullcontext())
    early, late = datetime(2026, 1, 5, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)
    db = fake_db(
        [(A, 3)],  # tools linked: A has three, B none
        [(A, 12, late)],  # devices
        [(A, 40)],  # people
        [(A, 9, 7)],  # checks
        [(A, 5, early)],  # alerts
    )
    out = asyncio.run(ep.client_onboarding(NS(tenant_id=OWNER), db, None))
    assert [r.client_name for r in out] == [
        "Acme",
        "Zed Co",
    ], "B has nothing done so it is first, and the owner's own tenant is not a client"
    assert [r.done for r in out] == [0, 5]
    zed = out[1]
    assert zed.first_data_at == early and zed.next_step is None and "7 met" in zed.steps[3].detail
    assert out[0].first_data_at is None and out[0].next_step.startswith("Link this client")


def test_the_csv_has_a_yes_or_no_per_step_the_next_step_and_never_a_formula():
    import csv
    import io

    done = build_row(CID, '=HYPERLINK("http://x")', Facts(tools=1, devices=1, people=1, checks=1, checks_met=1, alerts=1))
    part = build_row(uuid.uuid4(), "Birch", Facts(tools=2, devices=10))
    rows = list(csv.reader(io.StringIO(onboarding_csv([part, done]))))
    assert rows[0] == [
        "Client",
        "Percent",
        "Steps done",
        "Steps",
        "Tools linked",
        "Devices seen",
        "People seen",
        "Checks run",
        "Alerts arriving",
        "Next step",
        "First data",
    ]
    assert rows[1][:4] == ["Birch", "40", "2", "5"] and rows[1][4:9] == ["yes", "yes", "no", "no", "no"]
    assert "Microsoft 365 people" in rows[1][9]
    assert rows[2][0].startswith("'="), "a client name that starts with = is made text"
    assert rows[2][4:9] == ["yes"] * 5 and rows[2][9] == ""
