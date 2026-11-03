"""Domain expiry alerts: which domains are looked up and when, what a lookup that failed means, and which alert a registration end raises (once per threshold, never for an unknown)."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from app.services import domain_expiry as de
from app.services.domain_expiry import Known, band, detect_expiring, due_for_lookup, look_up, run_expiry_check
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
T = uuid.uuid4()
U = uuid.uuid4()


def days(n):
    return NOW + timedelta(days=n)


def known(domain, *, expires=None, checked=None, error=None, tenant=T):
    return Known(tenant, domain, expires, checked, error)


def rdap(expires=None, registered="2015-01-01T00:00:00Z"):
    events = [{"eventAction": "registration", "eventDate": registered}]
    if expires:
        events.append({"eventAction": "expiration", "eventDate": expires})
    return json.dumps({"events": events}).encode()


# ---- thresholds --------------------------------------------------------------------------------------------------------------------------------------------


def test_bands_by_days_left():
    assert [band(n) for n in (-1, 0, 7, 8, 14, 15, 30, 31, 400)] == ["expired", "7", "7", "14", "14", "30", "30", None, None]


def row(domain, expires, tenant=T):
    return Known(tenant, domain, expires, NOW - timedelta(hours=1))


def test_each_threshold_raises_with_its_severity_and_a_key_of_its_own():
    got = {f.key: (f.severity, f.title) for _, f in detect_expiring([row("a.com", days(25)), row("b.com", days(10)), row("c.com", days(3)), row("d.com", NOW - timedelta(days=2))], NOW)}
    assert got["a.com:30"][0] == "low" and "expires in 25 days" in got["a.com:30"][1]
    assert got["b.com:14"][0] == "medium"
    assert got["c.com:7"][0] == "high"
    assert got["d.com:expired"] == ("high", "Domain d.com has expired")


def test_a_far_off_or_unknown_end_raises_nothing():
    assert detect_expiring([row("a.com", days(200)), row("b.com", None)], NOW) == []


def test_the_expired_alert_mentions_the_takeover_risk_and_the_others_mention_the_usual_cause():
    out = {f.key: f.summary for _, f in detect_expiring([row("a.com", NOW - timedelta(days=1)), row("b.com", days(5))], NOW)}
    assert "anyone can register it" in out["a.com:expired"]
    assert "expired card" in out["b.com:7"]


def test_the_alert_key_stays_the_same_within_a_threshold_so_it_is_raised_once_not_daily():
    a = detect_expiring([row("a.com", days(12))], NOW)[0][1].key
    b = detect_expiring([row("a.com", days(12))], NOW + timedelta(days=3))[0][1].key  # 9 days left: still the 14 band
    c = detect_expiring([row("a.com", days(12))], NOW + timedelta(days=6))[0][1].key  # 6 days left: the 7 band, a new alert
    assert a == b == "a.com:14" and c == "a.com:7"


# ---- which domains are looked up ----------------------------------------------------------------------------------------------------------------------------


def test_never_checked_domains_go_first_then_failures_then_those_nearest_their_end():
    domains = [(T, d) for d in ("stale.com", "failed.com", "soon.com", "new.com", "fresh.com")]
    k = {
        (T, "stale.com"): known("stale.com", expires=days(300), checked=NOW - timedelta(days=8)),
        (T, "failed.com"): known("failed.com", error="x", checked=NOW - timedelta(days=2)),
        (T, "soon.com"): known("soon.com", expires=days(10), checked=NOW - timedelta(days=2)),
        (T, "fresh.com"): known("fresh.com", expires=days(300), checked=NOW - timedelta(days=2)),
    }
    assert [d for _, d in due_for_lookup(domains, k, NOW)] == ["new.com", "failed.com", "soon.com", "stale.com"]  # fresh.com is left alone


def test_a_recent_check_is_not_repeated_and_near_the_end_it_is_checked_daily_not_weekly():
    k = {(T, "a.com"): known("a.com", expires=days(10), checked=NOW - timedelta(hours=5)), (T, "b.com"): known("b.com", error="x", checked=NOW - timedelta(hours=5))}
    assert due_for_lookup([(T, "a.com"), (T, "b.com")], k, NOW) == []
    k2 = {(T, "a.com"): known("a.com", expires=days(10), checked=NOW - timedelta(hours=25))}
    assert due_for_lookup([(T, "a.com")], k2, NOW) == [(T, "a.com")]


def test_a_pass_looks_up_at_most_the_ceiling_and_the_same_domain_for_two_clients_is_two_lookups():
    domains = [(T, f"d{i:02d}.com") for i in range(de.MAX_LOOKUPS_PER_PASS + 15)]
    assert len(due_for_lookup(domains, {}, NOW)) == de.MAX_LOOKUPS_PER_PASS
    assert sorted(due_for_lookup([(T, "a.com"), (U, "a.com")], {}, NOW), key=str) == sorted([(T, "a.com"), (U, "a.com")], key=str)


# ---- a lookup -----------------------------------------------------------------------------------------------------------------------------------------------


def test_a_lookup_returns_the_end_date_and_calls_the_public_record_for_the_domain():
    seen = []

    async def fetch(url):
        seen.append(url)
        return rdap("2027-02-01T00:00:00Z")

    got = asyncio.run(look_up("acme.com", fetch))
    assert seen == ["https://rdap.org/domain/acme.com"]
    assert got.error is None and got.expires_at == datetime(2027, 2, 1, tzinfo=UTC) and got.registered.year == 2015


def test_a_lookup_that_fails_or_has_no_end_date_is_an_error_with_a_reason_never_a_date():
    async def refused(url):
        raise PermissionError("blocked")

    async def junk(url):
        return b"<html>not rdap</html>"

    async def no_end(url):
        return rdap(None)

    a, b, c = (asyncio.run(look_up("a.com", f)) for f in (refused, junk, no_end))
    assert a.expires_at is None and "could not be fetched (PermissionError)" in a.error
    assert b.expires_at is None and "not understood" in b.error
    assert c.expires_at is None and "no expiry date" in c.error


# ---- the pass -----------------------------------------------------------------------------------------------------------------------------------------------


class FakeDb:
    def __init__(self, seen, stored):
        self.seen, self.stored, self.writes = seen, stored, []

    async def execute(self, stmt, *a, **kw):
        text = str(stmt)
        if "DISTINCT" in text and "dmarc_reports" in text:
            return NS(all=lambda: self.seen)
        if "FROM domain_registrations" in text:
            return NS(scalars=lambda: NS(all=lambda: self.stored))
        self.writes.append(stmt)
        return NS(rowcount=1)

    def begin_nested(self):
        class Ctx:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

        return Ctx()


def stored(domain, expires, checked, error=None, tenant=T):
    return NS(tenant_id=tenant, domain=domain, expires_at=expires, checked_at=checked, error=error)


def compiled(stmt):
    c = stmt.compile(dialect=postgresql.dialect())
    return str(c), c.params


def test_a_pass_stores_what_it_found_and_alerts_for_a_domain_ending_soon():
    async def fetch(url):
        return rdap((NOW + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    db = FakeDb([(T, "acme.com")], [])
    looked, made = asyncio.run(run_expiry_check(db, fetch, NOW))
    assert (looked, made) == (1, 1)
    sql0, p0 = compiled(db.writes[0])
    assert "ON CONFLICT (tenant_id, domain) DO UPDATE" in sql0 and p0["domain"] == "acme.com" and p0["error"] is None
    sql1, p1 = compiled(db.writes[1])
    assert "ON CONFLICT (id) DO NOTHING" in sql1
    assert p1["tenant_id"] == T and p1["category"] == "domain" and p1["severity"] == "high" and p1["title"] == "Domain acme.com expires in 5 days"


def test_a_failed_lookup_is_stored_with_its_reason_and_raises_no_alert():
    async def fetch(url):
        raise TimeoutError()

    db = FakeDb([(T, "acme.com")], [])
    assert asyncio.run(run_expiry_check(db, fetch, NOW)) == (1, 0)
    _, p = compiled(db.writes[0])
    assert p["expires_at"] is None and "TimeoutError" in p["error"] and len(db.writes) == 1


def test_a_domain_checked_recently_is_not_looked_up_again_but_its_stored_end_still_alerts():
    async def fetch(url):
        raise AssertionError("must not be called")

    db = FakeDb([(T, "acme.com")], [stored("acme.com", NOW + timedelta(days=20), NOW - timedelta(hours=2))])
    assert asyncio.run(run_expiry_check(db, fetch, NOW)) == (0, 1)
    assert compiled(db.writes[0])[1]["severity"] == "low"


def test_a_stored_domain_no_longer_in_the_reports_raises_nothing():
    async def fetch(url):
        raise AssertionError("must not be called")

    db = FakeDb([], [stored("gone.com", NOW + timedelta(days=2), NOW - timedelta(hours=2))])
    assert asyncio.run(run_expiry_check(db, fetch, NOW)) == (0, 0)
    assert db.writes == []


def test_a_database_failure_is_swallowed_so_the_mailbox_loop_keeps_going():
    class Broken(FakeDb):
        async def execute(self, *a, **k):
            raise RuntimeError("down")

    async def fetch(url):
        return b""

    assert asyncio.run(run_expiry_check(Broken([], []), fetch, NOW)) == (0, 0)
