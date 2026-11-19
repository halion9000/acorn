"""A custom month range for the Metrics pages instead of the newest N months."""

import pytest
from app.services import month_window as mw
from app.services import ticket_metrics as tm
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

MONTHS = ["2026-07", "2026-08", "2026-09", "2026-10", "2026-11"]


def test_a_range_needs_both_months_in_the_right_form_and_a_backwards_one_is_turned_round():
    assert mw.clean_window(None, None) is None
    assert mw.clean_window("2026-03", "2026-05") == ("2026-03", "2026-05")
    assert mw.clean_window("2026-05", "2026-03") == ("2026-03", "2026-05")
    for bad in [("2026-03", None), (None, "2026-03"), ("2026-13", "2026-14"), ("March", "May"), ("2026-3", "2026-5")]:
        with pytest.raises(ValueError):
            mw.clean_window(*bad)


def test_the_newest_months_are_picked_unless_a_range_is_set_and_then_only_the_months_inside_it():
    assert mw.pick_months(MONTHS, 2) == ["2026-10", "2026-11"]
    assert mw.pick_months(MONTHS, 0) == []
    token = mw._window.set(("2026-08", "2026-10"))
    try:
        assert mw.pick_months(MONTHS, 2) == ["2026-08", "2026-09", "2026-10"], "the range wins over the count"
        assert mw.pick_months(MONTHS, 0) == ["2026-08", "2026-09", "2026-10"]
        assert mw.pick_months(["2020-01"], 3) == []
    finally:
        mw._window.reset(token)
    assert mw.pick_months(MONTHS, 2) == ["2026-10", "2026-11"], "the range is gone after the request"


def _app() -> TestClient:
    router = APIRouter(dependencies=[Depends(mw.month_window)])

    @router.get("/pick")
    async def pick(months: int = 2):
        return {"months": mw.pick_months(MONTHS, months), "window": mw.chosen_window()}

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_range_from_the_address_reaches_the_handler_and_does_not_leak_into_the_next_request():
    c = _app()
    assert c.get("/pick?months=2").json()["months"] == ["2026-10", "2026-11"]
    got = c.get("/pick?months=2&start=2026-08&end=2026-09").json()
    assert got["months"] == ["2026-08", "2026-09"] and got["window"] == ["2026-08", "2026-09"]
    assert c.get("/pick?months=2").json() == {"months": ["2026-10", "2026-11"], "window": None}


def test_a_half_or_bad_range_is_refused_with_a_reason():
    c = _app()
    for q in ("start=2026-08", "end=2026-08", "start=2026-8&end=2026-9", "start=x&end=y"):
        r = c.get(f"/pick?{q}")
        assert r.status_code == 422 and "start month and an end month" in r.json()["detail"], q


STATS = {
    "months": ["2026-08", "2026-09", "2026-10"],
    "rows": [
        {"client_id": "5", "client_name": "A", "month": "2026-08", "created": 10, "resolved": 9, "responded": 10, "response_minutes": 100.0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
        {"client_id": "5", "client_name": "A", "month": "2026-09", "created": 20, "resolved": 19, "responded": 20, "response_minutes": 100.0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
        {"client_id": "6", "client_name": "B", "month": "2026-09", "created": 20, "resolved": 21, "responded": 20, "response_minutes": 300.0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
        {"client_id": "5", "client_name": "A", "month": "2026-10", "created": 5, "resolved": 5, "responded": 0, "response_minutes": 0.0, "created_by_type": {}, "resolved_by_agent": {}, "critical": 0, "high": 0},
    ],
    "open_now": [],
}


def test_each_month_of_the_ticket_summary_carries_its_own_average_first_response():
    out = tm.summarize(STATS, 3)
    assert [(s["month"], s["first_response_minutes"]) for s in out["series"]] == [("2026-08", 10.0), ("2026-09", 10.0), ("2026-10", None)]
    assert tm.summarize(STATS, 3, "6")["series"][1]["first_response_minutes"] == 15.0, "one client's month, not the whole"


def test_a_custom_range_covers_exactly_those_months_in_the_ticket_summary():
    token = mw._window.set(("2026-08", "2026-09"))
    try:
        out = tm.summarize(STATS, 12)
    finally:
        mw._window.reset(token)
    assert out["months"] == ["2026-08", "2026-09"] and out["created"] == 50
