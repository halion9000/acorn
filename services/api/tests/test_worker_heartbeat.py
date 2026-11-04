"""Background workers report each pass; one that goes quiet or whose last pass failed is shown, and a worker that has not had its first turn yet is waiting, not late."""

import asyncio

import pytest
from app.api.v1.endpoints.health import platform_warnings
from app.services import worker_heartbeat as wh


@pytest.fixture(autouse=True)
def clean():
    wh.reset()
    yield
    wh.reset()


def status(name, now):
    return next(r for r in wh.snapshot(now) if r["name"] == name)["status"]


def test_a_worker_is_waiting_until_its_first_turn_is_overdue_and_then_late():
    wh.expect("dmarc", 1800, first_turn_after_seconds=120, now=0)
    assert status("dmarc", 60) == "waiting"
    assert status("dmarc", 120 + 1800 * 2.5) == "waiting"  # right on the edge
    assert status("dmarc", 120 + 1800 * 2.5 + 1) == "late"


def test_a_worker_that_beats_is_ok_and_goes_late_after_two_and_a_half_intervals_with_a_floor():
    wh.expect("sweep", 30, now=0)
    wh.beat("sweep", now=10)
    assert status("sweep", 10 + 119) == "ok"  # a 30 second worker is allowed the 120 second floor, not 75
    assert status("sweep", 10 + 121) == "late"
    wh.expect("minute", 60, now=0)
    wh.beat("minute", now=0)
    assert status("minute", 150) == "ok" and status("minute", 151) == "late"  # 2.5 intervals is above the floor here
    wh.expect("slow", 1800, now=0)
    wh.beat("slow", now=0)
    assert status("slow", 4500) == "ok" and status("slow", 4501) == "late"


def test_a_pass_that_failed_is_failing_not_ok_and_the_next_good_pass_clears_it():
    wh.expect("w", 300, now=0)
    wh.beat("w", error="OperationalError", now=5)
    row = next(r for r in wh.snapshot(10) if r["name"] == "w")
    assert (row["status"], row["last_error"], row["passes"], row["seconds_since_pass"]) == ("failing", "OperationalError", 1, 5)
    wh.beat("w", now=20)
    assert status("w", 25) == "ok" and next(r for r in wh.snapshot(25) if r["name"] == "w")["last_error"] is None


def test_the_worst_come_first_and_an_unregistered_worker_is_ignored():
    wh.beat("nobody-registered", now=1)  # a beat from a worker that never registered is ignored
    wh.reset()
    wh.expect("fine", 60, now=0)
    wh.expect("failing", 60, now=0)
    wh.expect("stuck", 60, now=0)
    wh.beat("fine", now=95)
    wh.beat("failing", error="X", now=95)
    rows = wh.snapshot(100)
    assert [(r["name"], r["status"]) for r in rows] == [("failing", "failing"), ("stuck", "waiting"), ("fine", "ok")]
    assert "nobody-registered" not in [r["name"] for r in rows]


def test_the_error_is_a_short_reason_never_a_long_message():
    wh.expect("w", 60, now=0)
    wh.beat("w", error="x" * 500, now=1)
    assert len(next(iter(wh.snapshot(2)))["last_error"]) == 80


def warn(workers):
    return platform_warnings(down=[], disk=None, pending=None, core_feed=None, device_feeds=[], signins=None, workers=workers)


def test_the_health_page_warns_in_plain_words_of_quiet_and_failing_workers_and_says_nothing_otherwise():
    quiet = {"name": "dmarc_ingest", "status": "late", "seconds_since_pass": 5400, "last_error": None}
    never = {"name": "retention", "status": "late", "seconds_since_pass": None, "last_error": None}
    failing = {"name": "platform_watch", "status": "failing", "seconds_since_pass": 30, "last_error": "TimeoutError"}
    ok = {"name": "alert_suppression", "status": "ok", "seconds_since_pass": 10, "last_error": None}
    waiting = {"name": "x", "status": "waiting", "seconds_since_pass": None, "last_error": None}
    out = {w["key"]: w for w in warn([quiet, never, failing, ok, waiting])}
    assert out["workers_quiet"]["level"] == "error" and "dmarc_ingest (90 minutes since its last pass)" in out["workers_quiet"]["text"] and "retention (never ran)" in out["workers_quiet"]["text"]
    assert out["workers_failing"]["level"] == "warn" and "platform_watch (TimeoutError)" in out["workers_failing"]["text"]
    assert "alert_suppression" not in str(out) and "x (" not in str(out)
    assert warn([ok, waiting]) == [] and warn(None) == [] and warn([]) == []


def test_each_worker_registers_itself_and_beats_after_a_pass_and_records_a_failed_one(monkeypatch):
    from app.workers import suppression_sweeper as sw

    class Stop(Exception):
        pass

    async def fake_sweep(session):
        return {"hidden": 0, "expired": 0, "restored": 0}

    async def fake_stale(session, days, exempt, now=None):
        return 0  # the hourly stale pass runs on the first turn too

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            return None

    sleeps = []

    async def sleep(n):
        sleeps.append(n)
        if len(sleeps) >= 2:
            raise Stop()

    monkeypatch.setattr(sw, "sweep", fake_sweep)
    monkeypatch.setattr(sw, "sweep_stale", fake_stale)
    monkeypatch.setattr(sw, "mark_platform", lambda s: None)
    with pytest.raises(Stop):
        asyncio.run(sw.run_suppression_sweeper(sleep=sleep, session_factory=lambda: Session()))
    row = wh.snapshot()[0]
    assert (row["name"], row["status"], row["passes"], row["interval_seconds"]) == ("alert_suppression", "ok", 1, 60)

    async def failing_sweep(session):
        raise RuntimeError("secret detail that must not be kept")

    wh.reset()
    sleeps.clear()
    monkeypatch.setattr(sw, "sweep", failing_sweep)
    with pytest.raises(Stop):
        asyncio.run(sw.run_suppression_sweeper(sleep=sleep, session_factory=lambda: Session()))
    row = wh.snapshot()[0]
    assert (row["status"], row["last_error"]) == ("failing", "RuntimeError")  # the type, not the message


def test_a_worker_that_backs_off_after_a_failure_is_failing_during_its_long_wait_not_late():
    wh.expect("mail", 60, now=0)
    wh.beat("mail", error="MailError", now=0, next_within_seconds=960)  # waits 16 intervals before its next try
    assert status("mail", 2000) == "failing"
    assert status("mail", 2401) == "late"  # 2.5 x 960: it really has gone quiet
    wh.beat("mail", now=3000)  # a good pass puts it back on its own clock
    assert status("mail", 3000 + 149) == "ok" and status("mail", 3000 + 151) == "late"


def test_the_alert_email_loop_registers_beats_and_records_a_failed_cycle_with_its_backed_off_wait(monkeypatch):
    from app.workers import alert_email_worker as ae

    class Stop(Exception):
        pass

    results = iter([ae.RunResult(sent=1), ae.RunResult(error="x"), RuntimeError("boom with detail")])

    async def fake_run_once(**kw):
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    waits = []

    async def sleep(n):
        waits.append(n)
        if len(waits) >= 3:
            raise Stop()

    monkeypatch.setattr(ae, "run_once", fake_run_once)
    monkeypatch.setattr(ae.settings, "ALERT_EMAIL_POLL_INTERVAL_SECONDS", 60)
    with pytest.raises(Stop):
        asyncio.run(ae.run_forever(mailer_factory=lambda: object(), sleep=sleep))
    row = wh.snapshot()[0]
    assert waits == [60, 120, 240]
    assert (row["name"], row["passes"], row["status"], row["last_error"]) == ("alert_email", 3, "failing", "RuntimeError")  # the type, not the message


def _stop_after(n):
    class Stop(Exception):
        pass

    count = {"n": 0}

    async def sleep(_):
        count["n"] += 1
        if count["n"] >= n:
            raise Stop()

    return Stop, sleep


def test_hunt_scheduler_oauth_refresh_and_weekly_digest_each_register_and_report_good_and_failed_passes(monkeypatch):
    from app.workers import hunt_scheduler as hs
    from app.workers import oauth_refresh as orf
    from app.workers import weekly_digest_task as wd

    for mod, name, ok in (
        (hs, "hunt_scheduler", 0),
        (orf, "oauth_refresh", {"checked": 0, "refreshed": 0, "failed": 0}),
        (wd, "weekly_digest", {"tenants": 0, "generated": 0, "failed": 0}),
    ):
        for outcome in ("ok", "fail"):
            wh.reset()
            Stop, sleep = _stop_after(1)

            async def run_once(ok=ok, outcome=outcome):
                if outcome == "fail":
                    raise ValueError("secret detail")
                return ok

            monkeypatch.setattr(mod, "run_once", run_once)
            monkeypatch.setattr(mod.asyncio, "sleep", sleep)
            if mod is wd:
                import datetime as dt

                class Monday(dt.datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return cls(2026, 11, 2, 0, 10, tzinfo=tz)  # a Monday, hour 0

                monkeypatch.setattr(wd, "datetime", Monday)
            with pytest.raises(Stop):
                asyncio.run(mod.run_forever())
            (row,) = wh.snapshot()
            assert row["name"] == name and row["passes"] == 1, (name, outcome)
            assert (row["status"], row["last_error"]) == (("ok", None) if outcome == "ok" else ("failing", "ValueError")), (name, outcome)


def test_a_failing_hourly_stale_pass_shows_as_a_failing_worker_not_a_silent_one(monkeypatch):
    from app.workers import suppression_sweeper as sw

    class Stop(Exception):
        pass

    async def fine_sweep(session):
        return {"hidden": 0, "expired": 0, "restored": 0}

    async def failing_stale(session, days, exempt, now=None):
        raise RuntimeError("secret detail that must not be kept")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def commit(self):
            return None

    sleeps = []

    async def sleep(n):
        sleeps.append(n)
        if len(sleeps) >= 2:
            raise Stop()

    wh.reset()
    monkeypatch.setattr(sw, "sweep", fine_sweep)
    monkeypatch.setattr(sw, "sweep_stale", failing_stale)
    monkeypatch.setattr(sw, "mark_platform", lambda s: None)
    with pytest.raises(Stop):
        asyncio.run(sw.run_suppression_sweeper(sleep=sleep, session_factory=lambda: Session()))
    row = wh.snapshot()[0]
    assert (row["status"], row["last_error"]) == ("failing", "RuntimeError")
