"""The DMARC new-sender alert: something that never sent as a client's domain before, and sends now, is raised once, with the mail that failed counted.

Only a domain whose reports go back far enough to know who its senders are is judged (the first weeks of reports would otherwise call every sender new), and a stray address that sends only a handful of messages is not.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services.dmarc_alerts import MIN_HISTORY_DAYS, NEW_SENDER_RULE_ID, detect_new_senders, run_new_sender_detection
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
TENANT = uuid.uuid4()


def row(ip, count, ok=True, spf=("amazonses.com",), dkim=("acme.com",)):
    return {"ip": ip, "count": count, "pass": ok, "spf": ok, "dkim": ok, "spf_domains": list(spf), "dkim_domains": list(dkim), "disposition": "none"}


def report(days_ago, rows, *, domain="acme.com", tenant=TENANT):
    return NS(tenant_id=tenant, domain=domain, end_at=NOW - timedelta(days=days_ago), total=sum(r["count"] for r in rows), passed=sum(r["count"] for r in rows if r["pass"]), failed=0, rows=rows)


def history(*rows_list):
    """Weeks of reports old enough to know who the senders are, one a few days apart, the oldest well beyond the baseline."""
    return [report(MIN_HISTORY_DAYS + 20 - 3 * i, rows) for i, rows in enumerate(rows_list)]


KNOWN = [row("40.107.1.1", 200, spf=("outlook.com",), dkim=("acme.com",))]


def found(reports):
    return detect_new_senders(reports, NOW)


def test_an_unknown_address_that_never_sent_before_and_sends_a_dozen_messages_now_is_raised_once_with_its_failures():
    out = found([*history(KNOWN, KNOWN, KNOWN), report(2, [row("203.0.113.9", 12, ok=False, spf=("evil.example",), dkim=()), row("203.0.113.9", 3, ok=True, spf=("evil.example",), dkim=())])])
    assert len(out) == 1
    f = out[0].finding
    assert out[0].tenant_id == TENANT and f.rule_id == NEW_SENDER_RULE_ID
    assert f.title == "A new sender is sending as acme.com: 203.0.113.9" and f.severity == "high"
    assert ("Messages in the last 7 days", "15, of which 12 failed DMARC") in f.fields
    assert f.ips == ["203.0.113.9"] and f.key == "acme.com:203.0.113.9"


def test_a_known_service_that_starts_sending_is_named_and_one_that_passes_everything_is_low():
    out = found([*history(KNOWN, KNOWN, KNOWN), report(1, [row("167.89.1.1", 40, spf=("sendgrid.net",), dkim=("acme.com",))])])
    assert len(out) == 1 and out[0].finding.title == "A new sender is sending as acme.com: SendGrid" and out[0].finding.severity == "low"
    assert out[0].finding.key == "acme.com:SendGrid"
    mixed = found([*history(KNOWN, KNOWN, KNOWN), report(1, [row("167.89.1.1", 40, spf=("sendgrid.net",), dkim=("acme.com",)), row("167.89.1.2", 10, ok=False, spf=("sendgrid.net",), dkim=())])])
    assert len(mixed) == 1 and mixed[0].finding.severity == "medium" and ("Addresses", "167.89.1.1, 167.89.1.2") in mixed[0].finding.fields


def test_a_sender_seen_before_is_not_new_and_a_stray_address_with_only_a_few_messages_is_ignored():
    assert found([*history(KNOWN, KNOWN, KNOWN), report(1, KNOWN)]) == []
    assert found([*history(KNOWN, KNOWN, KNOWN), report(1, [row("203.0.113.9", 4, ok=False, spf=("evil.example",), dkim=())])]) == [], "four messages is a stray, not a sender"
    earlier = [row("203.0.113.9", 50, spf=("evil.example",), dkim=())]
    assert found([*history(KNOWN, earlier, KNOWN), report(1, earlier)]) == [], "it sent weeks ago, so it is not new now"


def test_nothing_is_judged_until_the_reports_go_back_far_enough_and_another_clients_senders_do_not_count():
    young = [report(MIN_HISTORY_DAYS - 3, KNOWN), report(1, [row("203.0.113.9", 30, ok=False, spf=("evil.example",), dkim=())])]
    assert found(young) == [], "the first weeks of reports: everyone would look new"
    other_client = [*history(KNOWN, KNOWN, KNOWN), report(1, [row("203.0.113.9", 30, ok=False, spf=("evil.example",), dkim=())], tenant=uuid.uuid4())]
    assert found(other_client) == [], "a client with no history of its own is not judged on another's"
    other_domain = [*history(KNOWN, KNOWN, KNOWN), report(1, [row("40.107.1.1", 30, spf=("outlook.com",), dkim=("acme.com",))], domain="other.org")]
    assert found(other_domain) == [], "a domain with no history of its own is not judged on another's"


def test_a_report_older_than_a_week_is_baseline_only_and_each_new_sender_is_raised_separately():
    out = found([*history(KNOWN, KNOWN, KNOWN), report(12, [row("198.51.100.4", 30, ok=False, spf=("x.example",), dkim=())]), report(1, [row("203.0.113.9", 20, ok=False, spf=("y.example",), dkim=()), row("203.0.113.10", 20, ok=False, spf=("z.example",), dkim=())])])
    assert sorted(o.finding.key for o in out) == ["acme.com:203.0.113.10", "acme.com:203.0.113.9"], "the address that sent 12 days ago is not new this week"


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


def test_saving_inserts_one_alert_per_new_sender_that_a_repeat_cannot_duplicate():
    reports = [*history(KNOWN, KNOWN, KNOWN), report(1, [row("203.0.113.9", 20, ok=False, spf=("y.example",), dkim=())])]
    db = FakeDb(reports)
    assert asyncio.run(run_new_sender_detection(db, NOW)) == 1
    p = db.statements[0].compile(dialect=postgresql.dialect()).params
    assert "ON CONFLICT (id) DO NOTHING" in str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert p["tenant_id"] == TENANT and p["category"] == "email" and p["connector_type"] == "dmarc" and p["rule_id"] == NEW_SENDER_RULE_ID and p["severity"] == "high"
    db2 = FakeDb(reports)
    asyncio.run(run_new_sender_detection(db2, NOW + timedelta(days=2)))
    assert db2.statements[0].compile(dialect=postgresql.dialect()).params["id"] == p["id"], "the same sender on a later pass is the same alert"


def test_a_failure_while_saving_is_swallowed():
    class Broken(FakeDb):
        async def execute(self, stmt, *a, **kw):
            raise RuntimeError("database went away")

    assert asyncio.run(run_new_sender_detection(Broken([]), NOW)) == 0
