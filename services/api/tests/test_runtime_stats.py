import asyncio

import pytest
from app.services import runtime_stats as rs


@pytest.fixture(autouse=True)
def _clean():
    rs.reset()
    yield
    rs.reset()


def test_loop_lag_reports_worst_and_typical_over_the_window_and_flags_slow():
    assert rs.loop_lag(1000.0) == {"window_seconds": 300, "samples": 0}
    for i, lag in enumerate([0.0, 0.01, 0.02, 0.01, 2.5]):
        rs.note_loop_lag(900.0 + i, lag)
    rs.note_loop_lag(100.0, 9.0)  # outside the window
    out = rs.loop_lag(1000.0)
    assert out["samples"] == 5 and out["max_seconds"] == 2.5 and out["slow"] is True and out["typical_seconds"] == 0.01
    assert rs.loop_lag(1000.0)["window_seconds"] == 300


def test_a_negative_lag_is_clamped_and_quiet_loops_are_not_slow():
    rs.note_loop_lag(10.0, -0.3)
    assert rs.loop_lag(11.0)["max_seconds"] == 0.0 and rs.loop_lag(11.0)["slow"] is False


def test_routes_are_ranked_by_total_time_with_typical_p95_and_worst():
    for s in [0.1] * 18 + [1.0, 5.0]:
        rs.note_route("GET", "/devices", s)
    rs.note_route("GET", "/cheap", 0.01)
    rs.note_route("POST", "/ingest", 3.0)
    top = rs.slow_routes()
    assert [r["route"] for r in top] == ["GET /devices", "POST /ingest", "GET /cheap"]
    d = top[0]
    assert d["calls"] == 20 and d["total_seconds"] == 7.8 and d["typical_seconds"] == 0.1 and d["worst_seconds"] == 5.0 and d["p95_seconds"] == 5.0
    assert len(rs.slow_routes(limit=1)) == 1


def test_the_table_is_bounded_and_drops_the_cheapest_route(monkeypatch):
    monkeypatch.setattr(rs, "ROUTES_KEPT", 3)
    for i, s in enumerate([5.0, 0.001, 3.0]):
        rs.note_route("GET", f"/r{i}", s)
    rs.note_route("GET", "/new", 1.0)
    keys = {r["route"] for r in rs.slow_routes(limit=10)}
    assert keys == {"GET /r0", "GET /r2", "GET /new"}


async def test_the_sampler_records_readings_and_stops():
    rs.reset()
    rs.LOOP_TICK_SECONDS = 0.01
    try:
        rs.start_loop_sampler()
        rs.start_loop_sampler()
        await asyncio.sleep(0.15)
    finally:
        rs.stop_loop_sampler()
        rs.LOOP_TICK_SECONDS = 1.0
    assert rs.loop_lag(__import__("time").time())["samples"] >= 3
