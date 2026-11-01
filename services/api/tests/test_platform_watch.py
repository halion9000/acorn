"""The platform's self-check: what counts as a problem, that a change is told once, and that a failed mail is retried."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.alert_email.graph import MailError
from app.services.platform_watch import ConnectorSeen, Finding, changes, compose, evaluate
from app.workers import platform_watch_worker as worker

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def _look(**over):
    base = {
        "now": NOW,
        "core_feed_last_report": NOW - timedelta(minutes=2),
        "core_feed_sources": 3,
        "connectors": [],
        "connector_silent_after": timedelta(hours=6),
        "disk_free_percent": 60.0,
        "memory_available_percent": 40.0,
    }
    base.update(over)
    return base


def test_a_healthy_platform_has_no_findings():
    assert evaluate(**_look()) == []


def test_core_silent_for_over_fifteen_minutes_is_critical_and_says_for_how_long():
    found = evaluate(**_look(core_feed_last_report=NOW - timedelta(minutes=40)))
    assert [(f.key, f.severity) for f in found] == [("core_feed", "critical")]
    assert "40 minutes" in found[0].message


def test_core_never_connected_is_not_an_alarm_but_connected_and_never_reported_is():
    assert evaluate(**_look(core_feed_sources=0, core_feed_last_report=None)) == []
    assert evaluate(**_look(core_feed_sources=2, core_feed_last_report=None))[0].key == "core_feed"


def test_a_connector_quiet_past_the_limit_is_a_warning_and_a_new_one_is_not():
    quiet = ConnectorSeen("Huntress", "Acme", NOW - timedelta(hours=9))
    fresh = ConnectorSeen("Blumira", "Acme", NOW - timedelta(hours=1))
    new = ConnectorSeen("Petra", "Acme", None)
    found = evaluate(**_look(connectors=[quiet, fresh, new]))
    assert [f.key for f in found] == ["connector:Acme:Huntress"]
    assert found[0].severity == "warning"


def test_low_disk_warns_then_goes_critical_and_low_memory_warns():
    assert evaluate(**_look(disk_free_percent=12.0))[0].severity == "warning"
    assert evaluate(**_look(disk_free_percent=5.0))[0].severity == "critical"
    assert evaluate(**_look(memory_available_percent=4.0))[0].key == "memory"


def test_a_measurement_that_could_not_be_taken_is_not_an_alarm():
    assert evaluate(**_look(disk_free_percent=None, memory_available_percent=None)) == []


def test_changes_reports_new_and_cleared_and_not_a_problem_that_simply_stays():
    a, b = Finding("a", "warning", "A"), Finding("b", "critical", "B")
    assert changes({}, [a]) == ([a], [])
    assert changes({"a": a}, [a]) == ([], [])
    assert changes({"a": a, "b": b}, [a]) == ([], [b])
    # A warning that becomes critical is told again; critical falling to warning is not.
    assert changes({"d": Finding("d", "warning", "D")}, [Finding("d", "critical", "D")])[0][0].severity == "critical"
    assert changes({"d": Finding("d", "critical", "D")}, [Finding("d", "warning", "D")])[0] == []


def test_compose_names_the_problem_and_the_recovery():
    subject, body = compose([Finding("core_feed", "critical", "CORE has not reported for 40 minutes. More.")], [], server_name="vm1")
    assert "ACTION NEEDED" in subject and "40 minutes" in subject and "vm1" in body
    subject, _ = compose([], [Finding("disk", "warning", "The server disk has 12% free.")], server_name="vm1")
    assert subject.startswith("[A.C.O.R.N] Back to normal")


# ----------------------------------------------------------------- the worker


class _Mailer:
    configured = True

    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[tuple[list[str], str]] = []
        self.fail_times = fail_times

    async def send(self, recipients, subject, body):
        if self.fail_times:
            self.fail_times -= 1
            raise MailError("throttled", permanent=False)
        self.sent.append((recipients, subject))


def _factory(recipients):
    @asynccontextmanager
    async def factory():
        yield SimpleNamespace(recipients=recipients)

    return factory


def _patch_settings(monkeypatch, recipients):
    async def fake_get_settings(db):
        return SimpleNamespace(recipients=db.recipients)

    monkeypatch.setattr(worker, "get_settings", fake_get_settings)
    return _factory(recipients)


def _measure(last_report):
    async def fn(_factory, now):
        return _look(now=now, core_feed_last_report=last_report)

    return fn


def test_the_worker_mails_a_change_once_and_the_recovery_once(monkeypatch):
    factory = _patch_settings(monkeypatch, ["hal@goliveoak.com"])
    mailer, watch = _Mailer(), worker.Watch()

    async def go():
        silent = _measure(NOW - timedelta(minutes=40))
        await watch.step(session_factory=factory, mailer=mailer, now=NOW, measure_fn=silent)
        await watch.step(session_factory=factory, mailer=mailer, now=NOW, measure_fn=silent)  # still down: no second mail
        await watch.step(session_factory=factory, mailer=mailer, now=NOW, measure_fn=_measure(NOW))  # back

    asyncio.run(go())
    assert [s for _, s in mailer.sent][0].startswith("[A.C.O.R.N] ACTION NEEDED")
    assert len(mailer.sent) == 2 and mailer.sent[1][1].startswith("[A.C.O.R.N] Back to normal")


def test_a_failed_mail_is_retried_next_cycle(monkeypatch):
    factory = _patch_settings(monkeypatch, ["hal@goliveoak.com"])
    mailer, watch = _Mailer(fail_times=1), worker.Watch()

    async def go():
        silent = _measure(NOW - timedelta(minutes=40))
        first = await watch.step(session_factory=factory, mailer=mailer, now=NOW, measure_fn=silent)
        second = await watch.step(session_factory=factory, mailer=mailer, now=NOW, measure_fn=silent)
        return first, second

    first, second = asyncio.run(go())
    assert first["untold"] == 1 and second["untold"] == 0
    assert len(mailer.sent) == 1


def test_with_no_recipients_nothing_is_sent_and_nothing_piles_up(monkeypatch):
    factory = _patch_settings(monkeypatch, [])
    mailer, watch = _Mailer(), worker.Watch()
    result = asyncio.run(watch.step(session_factory=factory, mailer=mailer, now=NOW, measure_fn=_measure(NOW - timedelta(minutes=40))))
    assert mailer.sent == [] and result["untold"] == 0


def test_memory_reading_parses_meminfo(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal:       1000 kB\nMemFree: 10 kB\nMemAvailable:    250 kB\n", encoding="utf-8")
    assert worker.memory_available_percent(str(f)) == 25.0
    assert worker.memory_available_percent(str(tmp_path / "nope")) is None
