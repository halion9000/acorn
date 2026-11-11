"""The DMARC pass-rate drop alert: a ten-point fall week on week, with enough mail in both weeks, raises one alert per client, domain and week naming the senders whose failures grew."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services.dmarc_alerts import MIN_EMAILS, RULE_ID, detect_pass_rate_drops, run_pass_rate_detection
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)  # a Wednesday in ISO week 45
TENANT = uuid.uuid4()
OTHER = uuid.uuid4()


def report(days_ago, passed, failed, *, tenant=TENANT, domain="acme.com", rows=None):
    return NS(
        tenant_id=tenant,
        domain=domain,
        end_at=NOW - timedelta(days=days_ago),
        total=passed + failed,
        passed=passed,
        failed=failed,
        rows=rows or [],
    )


def rows(**by_ip):
    return [{"ip": ip, "count": n, "pass": ok} for ip, (n, ok) in by_ip.items()]


def drops(reports):
    return detect_pass_rate_drops(reports, NOW)


def test_a_fall_of_ten_points_or_more_raises_one_alert_with_both_rates():
    out = drops([report(10, 98, 2), report(2, 71, 29)])
    assert len(out) == 1
    d = out[0]
    assert d.tenant_id == TENANT
    assert d.finding.rule_id == RULE_ID and d.finding.title == "DMARC pass rate for acme.com fell from 98% to 71%"
    assert ("Pass rate this week", "71% of 100 messages") in d.finding.fields
    assert ("Pass rate the week before", "98% of 100 messages") in d.finding.fields
    assert d.finding.severity == "medium"


def test_a_smaller_fall_or_a_rise_raises_nothing_and_exactly_ten_points_does():
    assert drops([report(10, 98, 2), report(2, 90, 10)]) == []  # 8 points
    assert drops([report(10, 60, 40), report(2, 95, 5)]) == []  # it got better
    assert len(drops([report(10, 95, 5), report(2, 85, 15)])) == 1  # exactly 10 points


def test_a_quiet_week_never_raises_however_bad_the_rate_looks():
    assert drops([report(10, 98, 2), report(2, 0, MIN_EMAILS - 1)]) == []  # a handful of messages
    assert drops([report(10, 0, MIN_EMAILS - 1), report(2, 100, 0)]) == []
    assert len(drops([report(10, 98, 2), report(2, 0, MIN_EMAILS)])) == 1  # exactly enough


def test_a_rate_under_half_is_high_severity():
    assert drops([report(10, 98, 2), report(2, 40, 60)])[0].finding.severity == "high"


def test_reports_are_placed_in_a_week_by_when_they_ended_and_older_ones_are_ignored():
    out = drops(
        [report(20, 0, 500), report(10, 98, 2), report(8, 98, 2), report(2, 71, 29), report(-1, 0, 500)]
    )  # 20 days ago and a future one are in neither week
    assert len(out) == 1 and ("Pass rate the week before", "98% of 200 messages") in out[0].finding.fields


def test_clients_and_domains_are_judged_separately():
    reports = [
        report(10, 98, 2),
        report(2, 71, 29),  # acme.com drops
        report(10, 98, 2, domain="b.com"),
        report(2, 97, 3, domain="b.com"),  # b.com is fine
        report(10, 98, 2, tenant=OTHER),
        report(2, 50, 50, tenant=OTHER),  # the same domain for another client drops too
    ]
    got = sorted((str(d.tenant_id), d.finding.title) for d in drops(reports))
    assert got == sorted(
        [
            (str(TENANT), "DMARC pass rate for acme.com fell from 98% to 71%"),
            (str(OTHER), "DMARC pass rate for acme.com fell from 98% to 50%"),
        ]
    )


def test_it_names_the_senders_whose_failing_mail_grew_most_and_ignores_ones_that_did_not():
    before = report(10, 98, 2, rows=rows(**{"10.0.0.1": (98, True), "10.0.0.2": (2, False)}))
    now = report(
        2,
        71,
        29,
        rows=rows(**{"10.0.0.1": (71, True), "10.0.0.2": (2, False), "203.0.113.9": (20, False), "198.51.100.4": (7, False)}),
    )
    f = drops([before, now])[0].finding
    assert [v for k, v in f.fields if k == "Failing more"] == [
        "203.0.113.9: 20 failing messages this week, 0 the week before",
        "198.51.100.4: 7 failing messages this week, 0 the week before",
    ]
    assert f.ips == ["203.0.113.9", "198.51.100.4"]  # 10.0.0.2 failed the same amount both weeks: not listed


def test_when_no_single_address_explains_it_the_alert_says_so_instead_of_naming_none():
    f = drops([report(10, 98, 2), report(2, 71, 29)])[0].finding  # no per-sender rows stored
    assert [v for k, v in f.fields if k == "Failing more"] == [
        "No single sending address accounts for it; the failures are spread across many"
    ]
    assert f.ips == []


def test_the_same_drop_has_the_same_key_all_week_and_a_new_one_next_week():
    reports = [report(10, 98, 2), report(2, 71, 29)]
    a = detect_pass_rate_drops(reports, NOW)[0].finding.key
    b = detect_pass_rate_drops(reports, NOW + timedelta(hours=30))[0].finding.key  # still ISO week 45
    c = detect_pass_rate_drops([report(10 - 7, 98, 2), report(2 - 7, 71, 29)], NOW + timedelta(days=7))[0].finding.key
    assert a == b == "acme.com:2026-W45" and c == "acme.com:2026-W46"


def test_the_summary_says_reports_lag_and_names_both_explanations():
    s = drops([report(10, 98, 2), report(2, 71, 29)])[0].finding.summary
    assert "a day or more" in s and "stopped authenticating" in s and "sending as the domain" in s


class FakeDb:
    def __init__(self, reports):
        self.reports, self.statements = reports, []

    async def execute(self, stmt, *a, **kw):
        if "FROM dmarc_reports" in str(stmt):
            return NS(scalars=lambda: NS(all=lambda: self.reports))
        self.statements.append(stmt)
        return NS(rowcount=1)

    def begin_nested(self):
        class Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

        return Ctx()


def test_saving_inserts_one_email_alert_per_drop_for_the_clients_tenant_and_ignores_a_repeat():
    db = FakeDb([report(10, 98, 2), report(2, 71, 29)])
    made = asyncio.run(run_pass_rate_detection(db, NOW))
    assert made == 1 and len(db.statements) == 1
    stmt = db.statements[0]
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT (id) DO NOTHING" in sql
    p = stmt.compile(dialect=postgresql.dialect()).params
    assert p["tenant_id"] == TENANT and p["category"] == "email" and p["connector_type"] == "dmarc" and p["severity"] == "medium"
    assert p["rule_id"] == RULE_ID and "dmarc" in p["tags"]
    again = asyncio.run(run_pass_rate_detection(FakeDb([report(10, 98, 2), report(2, 71, 29)]), NOW))
    assert again == 1  # same input, same id: the database drops the duplicate, which the conflict clause above guarantees
    ids = {db.statements[0].compile(dialect=postgresql.dialect()).params["id"]}
    db2 = FakeDb([report(10, 98, 2), report(2, 71, 29)])
    asyncio.run(run_pass_rate_detection(db2, NOW + timedelta(hours=3)))
    assert db2.statements[0].compile(dialect=postgresql.dialect()).params["id"] in ids  # a later pass the same week computes the same id


def test_a_failure_while_saving_is_swallowed_so_the_mailbox_reader_keeps_going():
    class Broken(FakeDb):
        async def execute(self, stmt, *a, **kw):
            raise RuntimeError("database went away")

    assert asyncio.run(run_pass_rate_detection(Broken([]), NOW)) == 0


def _one_pass(monkeypatch, stored, alerts):
    from app.services import worker_heartbeat as wh
    from app.services.dmarc_mailbox import IngestResult
    from app.workers import dmarc_ingest_worker as w

    wh.reset()
    calls = []

    async def fake_ingest(*a, **kw):
        return IngestResult(stored=stored)

    async def fake_alerts():
        calls.append(1)
        return alerts

    class Stop(Exception):
        pass

    n = {"n": 0}

    async def sleep(_):
        n["n"] += 1
        if n["n"] >= 2:
            raise Stop()

    monkeypatch.setattr(w, "ingest_once", fake_ingest)
    monkeypatch.setattr(w, "raise_alerts", fake_alerts)

    async def fake_expiry():
        return (0, 0)

    monkeypatch.setattr(w, "check_expiry", fake_expiry)
    monkeypatch.setattr(w, "owner_id", lambda: uuid.uuid4())
    monkeypatch.setattr(w, "make_reader", lambda: NS(configured=True))
    try:
        asyncio.run(w.run_dmarc_ingest(sleep=sleep))
    except Stop:
        pass
    return calls, wh.snapshot()[0]


def test_the_mailbox_loop_checks_for_drops_only_after_it_stored_reports(monkeypatch):
    calls, row = _one_pass(monkeypatch, stored=3, alerts=1)
    assert calls == [1] and row["status"] == "ok"
    calls, _ = _one_pass(monkeypatch, stored=0, alerts=0)
    assert calls == []  # nothing new arrived: nothing to compare


def test_a_failure_in_the_alert_step_never_fails_the_read_of_the_mailbox(monkeypatch):
    from app.workers import dmarc_ingest_worker as w

    class Boom:
        def __call__(self):
            raise RuntimeError("no database")

    monkeypatch.setattr(w, "AsyncSessionLocal", Boom())
    assert asyncio.run(w.raise_alerts()) == 0
