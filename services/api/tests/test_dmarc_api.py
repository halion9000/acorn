"""The DMARC pages' data: per-client overview (worst first), one domain's trend and failing sources, mailbox status, and the setup lines."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import dmarc as ep
from app.db.database import Base
from app.models.dmarc import DmarcIngestState, DmarcReport
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.models.tenant import Tenant
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, IdentitySource, IdentityMfaUser, DmarcReport, DmarcIngestState)]
NOW = datetime.now(UTC)


class FakeResolver:
    """MX answers by domain; a domain not listed has none. `calls` counts the lookups made."""

    def __init__(self, mx=None, flaky=None, broken=()):
        self.mx_by_domain, self.flaky, self.broken, self.calls = mx or {}, dict(flaky or {}), set(broken), []

    async def mx(self, name):
        self.calls.append(name)
        if name in self.broken:
            raise RuntimeError("DNS is down")
        if self.flaky.get(name, 0) > 0:  # empty the first time(s), then the real answer
            self.flaky[name] -= 1
            return []
        return self.mx_by_domain.get(name, [])


@pytest.fixture(autouse=True)
def settings_and_rls(monkeypatch):
    ep._MX_CACHE.clear()
    @contextlib.asynccontextmanager
    async def plain(_db):
        yield

    monkeypatch.setattr(ep, "cross_tenant_reads", plain)
    monkeypatch.setattr(ep.settings, "DMARC_MAILBOX", "dmarc@goliveoak.com", raising=False)
    monkeypatch.setattr(ep.settings, "DMARC_OWNER_TENANT_ID", str(uuid.uuid4()), raising=False)


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


async def tenant(s, name, parent=None):
    t = Tenant(id=uuid.uuid4(), name=name, slug=name.lower().replace(" ", "-"), parent_tenant_id=parent)
    s.add(t)
    await s.flush()
    return t


def rep(tenant_id, domain, total, passed, days_ago=1, matched=True, rid=None, policy="none", rows=None):
    end = NOW - timedelta(days=days_ago)
    return DmarcReport(
        tenant_id=tenant_id,
        matched=matched,
        domain=domain,
        reporter="google.com",
        report_id=rid or uuid.uuid4().hex,
        begin_at=end - timedelta(days=1),
        end_at=end,
        policy=policy,
        total=total,
        passed=passed,
        failed=total - passed,
        rows=rows or [],
    )


def caller(owner):
    return SimpleNamespace(tenant_id=owner.id)


def test_the_overview_adds_up_each_client_domain_and_lists_the_worst_first():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme, birch = await tenant(s, "Acme", owner.id), await tenant(s, "Birch", owner.id)
        s.add_all([rep(acme.id, "acme.com", 100, 99), rep(acme.id, "acme.com", 100, 91, days_ago=2, policy="reject"), rep(birch.id, "birch.com", 50, 10), rep(birch.id, "old.com", 10, 10, days_ago=60)])
        await s.commit()
        return await ep.overview(caller(owner), s, days=30)

    out = run(body)
    assert [d.domain for d in out.domains] == ["birch.com", "acme.com"]  # birch.com is the worst (20%), the 60-day-old report is outside the window
    acme = out.domains[1]
    assert (acme.reports, acme.total, acme.passed, acme.failed, acme.pass_rate, acme.client_name) == (2, 200, 190, 10, 95.0, "Acme")
    assert acme.policy == "none"  # the newest report's published policy (the 1-day-old one)


def test_reports_nobody_could_be_matched_to_are_listed_apart_and_counted():
    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(rep(owner.id, "unknown.example", 5, 5, matched=False))
        await s.commit()
        return await ep.overview(caller(owner), s, days=30)

    out = run(body)
    assert out.domains[0].matched is False and out.domains[0].client_name == "Not matched to a client"
    assert out.status.unmatched_reports == 1


def test_one_owner_never_sees_another_owners_reports():
    async def body(s):
        mine, theirs = await tenant(s, "Mine"), await tenant(s, "Theirs")
        c_theirs = await tenant(s, "Their Client", theirs.id)
        s.add(rep(c_theirs.id, "theirs.com", 10, 10))
        await s.commit()
        out = await ep.overview(caller(mine), s, days=30)
        with pytest.raises(HTTPException) as e:
            await ep.domain_detail("theirs.com", caller(mine), s, days=30)
        return out, e.value.status_code

    out, code = run(body)
    assert out.domains == [] and code == 404


def test_a_domain_shows_its_daily_series_and_the_biggest_failing_sources():
    rows_a = [{"ip": "1.2.3.4", "count": 90, "pass": True, "header_from": "acme.com", "envelope_from": "acme.com", "disposition": "none"}, {"ip": "9.9.9.9", "count": 6, "pass": False, "header_from": "acme.com", "envelope_from": "evil.example", "disposition": "quarantine"}]
    rows_b = [{"ip": "9.9.9.9", "count": 4, "pass": False, "header_from": "acme.com", "envelope_from": "evil.example", "disposition": "quarantine"}, {"ip": "8.8.8.8", "count": 1, "pass": False, "header_from": "acme.com", "envelope_from": "x.example", "disposition": "none"}]

    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add_all([rep(acme.id, "acme.com", 96, 90, days_ago=1, rows=rows_a), rep(acme.id, "acme.com", 5, 0, days_ago=3, rows=rows_b)])
        await s.commit()
        return await ep.domain_detail("ACME.com.", caller(owner), s, days=30)

    d = run(body)
    assert (d.domain, d.reports, d.total, d.passed, d.failed) == ("acme.com", 2, 101, 90, 11)
    assert [p.total for p in d.series] == [5, 96] and d.series[0].day < d.series[1].day  # oldest first
    assert [(f.ip, f.count) for f in d.failing_sources] == [("9.9.9.9", 10), ("8.8.8.8", 1)]  # passing sources are not listed
    assert d.failing_sources[0].disposition == "quarantine"


def test_a_bad_domain_name_is_refused():
    async def body(s):
        owner = await tenant(s, "Owner")
        with pytest.raises(HTTPException) as e:
            await ep.domain_detail("not a domain!", caller(owner), s, days=30)
        return e.value.status_code

    assert run(body) == 422


def test_the_status_says_when_the_mailbox_was_last_read_and_what_went_wrong():
    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(DmarcIngestState(tenant_id=owner.id, last_run_at=NOW, last_error="HTTP 403 ErrorAccessDenied", stored=12, rejected=2))
        await s.commit()
        return (await ep.overview(caller(owner), s, days=7)).status

    st = run(body)
    assert (st.configured, st.mailbox, st.last_error, st.stored, st.rejected) == (True, "dmarc@goliveoak.com", "HTTP 403 ErrorAccessDenied", 12, 2)


def test_the_setup_gives_each_client_domain_an_alias_and_the_dns_line_for_your_zone():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme Dental", owner.id)
        s.add_all(
            [
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u1", upn="a@acmedental.com", snapshot_id=uuid.uuid4()),
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u2", upn="b@acmedental.com", snapshot_id=uuid.uuid4()),
                IdentitySource(tenant_id=acme.id, vendor="huntress", external_id="x", email="c@gmail.com"),  # a provider domain is not a client's
            ]
        )
        await s.commit()
        return await ep.setup(caller(owner), s, FakeResolver({'acmedental.com': ['mail.acmedental.com']}))

    out = run(body)
    assert (out.mailbox, out.mailbox_domain) == ("dmarc@goliveoak.com", "goliveoak.com")
    (line,) = out.lines
    assert (line.client_name, line.domain, line.alias) == ("Acme Dental", "acmedental.com", "acme-dental.dmarc@goliveoak.com")
    assert line.client_dmarc_rua == "rua=mailto:acme-dental.dmarc@goliveoak.com"
    assert (line.authorization_record_name, line.authorization_record_value) == ("acmedental.com._report._dmarc.goliveoak.com", "v=DMARC1")


def test_without_a_mailbox_the_setup_is_empty_and_the_status_says_not_configured(monkeypatch):
    monkeypatch.setattr(ep.settings, "DMARC_MAILBOX", "", raising=False)

    async def body(s):
        owner = await tenant(s, "Owner")
        await tenant(s, "Acme", owner.id)
        return await ep.setup(caller(owner), s, FakeResolver()), (await ep.overview(caller(owner), s, days=30)).status

    out, st = run(body)
    assert out.lines == [] and out.mailbox is None and st.configured is False


def test_the_managing_companys_own_domain_is_labelled_as_its_own_and_counts_as_matched():
    async def body(s):
        owner = await tenant(s, "Live Oak")
        s.add(rep(owner.id, "goliveoak.com", 20, 20, matched=True))
        await s.commit()
        return await ep.overview(caller(owner), s, days=30)

    out = run(body)
    assert (out.domains[0].client_name, out.domains[0].matched) == ("Live Oak (own)", True)
    assert out.status.unmatched_reports == 0


def test_aliases_are_readable_the_random_slug_tail_is_dropped_and_no_two_clients_share_one():
    def t(slug):
        return SimpleNamespace(slug=slug)

    names = ep.alias_names(
        {
            1: t("acme-dental-1a2b3c"),
            2: t("a-pup-above-inc-11e861"),
            3: t("birch-law"),  # no tail to drop
            4: t("twin-aaaaaa"),
            5: t("twin-bbbbbb"),  # would collide once the tails are gone: both keep the full slug
            6: t("Weird Name!-0f0f0f"),
        }
    )
    assert names[1] == "acme-dental" and names[2] == "a-pup-above-inc" and names[3] == "birch-law"
    assert (names[4], names[5]) == ("twin-aaaaaa", "twin-bbbbbb")
    assert names[6] == "weird-name"
    assert len(set(names.values())) == len(names)
    assert all(len(n) <= 48 for n in names.values())


def test_a_domain_with_no_mail_records_is_marked_and_one_with_mail_or_an_unclear_lookup_is_not():
    r = FakeResolver(mx={"mail.example": ["mx1.mail.example"], "null.example": [""], "slow.example": ["mx.slow.example"]}, flaky={"slow.example": 1}, broken=["down.example"])
    got = asyncio.run(ep.mail_domains(["mail.example", "none.example", "null.example", "slow.example", "down.example"], r))
    assert got == {
        "mail.example": True,
        "none.example": False,  # nothing, twice
        "null.example": False,  # the "null MX" (RFC 7505) says there is no mail here
        "slow.example": True,  # empty once, found on the second try
        "down.example": True,  # a failed lookup never hides a domain
    }
    assert r.calls.count("none.example") == 2 and r.calls.count("slow.example") == 2


def test_the_answers_are_remembered_for_an_hour_so_the_page_stays_quick():
    r = FakeResolver(mx={"mail.example": ["mx.mail.example"]})
    asyncio.run(ep.mail_domains(["mail.example", "none.example"], r, now=1000.0))
    first = len(r.calls)
    asyncio.run(ep.mail_domains(["mail.example", "none.example"], r, now=1000.0 + ep._MX_TTL_SECONDS - 1))
    assert len(r.calls) == first  # nothing asked again
    asyncio.run(ep.mail_domains(["mail.example"], r, now=1000.0 + ep._MX_TTL_SECONDS + 1))
    assert len(r.calls) == first + 1  # after the hour it is asked again


def test_the_setup_marks_each_line_with_whether_its_domain_has_mail():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add_all(
            [
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u1", upn="a@acme.com", snapshot_id=uuid.uuid4()),
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u2", upn="b@acme.com", snapshot_id=uuid.uuid4()),
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u3", upn="c@parked.example", snapshot_id=uuid.uuid4()),
            ]
        )
        await s.commit()
        return await ep.setup(caller(owner), s, FakeResolver({"acme.com": ["mx.acme.com"]}))

    out = run(body)
    assert {ln.domain: ln.has_mx for ln in out.lines} == {"acme.com": True, "parked.example": False}


def line_row(ip, count, ok=True, dkim=None, spf=None, disposition="none", reason="", spf_domains=(), dkim_domains=(), header_from="acme.com"):
    return {
        "ip": ip,
        "count": count,
        "disposition": disposition,
        "dkim": ok if dkim is None else dkim,
        "spf": ok if spf is None else spf,
        "pass": ok,
        "header_from": header_from,
        "envelope_from": header_from,
        "dkim_domains": list(dkim_domains),
        "spf_domains": list(spf_domains),
        "reason": reason,
    }


def test_every_message_lands_in_exactly_one_delivery_outcome():
    rows = [
        line_row("1.1.1.1", 50),  # passed and delivered
        line_row("2.2.2.2", 7, ok=False),  # failed but delivered (monitor-only)
        line_row("3.3.3.3", 5, ok=False, reason="forwarded"),  # delivered because the receiver overrode the policy
        line_row("4.4.4.4", 4, ok=False, disposition="quarantine"),
        line_row("5.5.5.5", 3, ok=False, disposition="reject"),
        line_row("6.6.6.6", 2, ok=False, disposition="quarantine", reason="forwarded"),  # what the receiver did decides: quarantined, not overridden
    ]
    assert [ep.delivery_class(r) for r in rows] == ["passed", "failed_delivered", "overridden", "quarantined", "rejected", "quarantined"]

    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add(rep(acme.id, "acme.com", 71, 50, rows=rows))
        await s.commit()
        return await ep.insights(caller(owner), s, days=30, domain=None, client_id=None)

    out = run(body)
    d = out.delivery
    assert (d.passed, d.failed_delivered, d.overridden, d.quarantined, d.rejected) == (50, 7, 5, 6, 3)
    assert out.emails == 71 == d.passed + d.failed_delivered + d.overridden + d.quarantined + d.rejected


def test_failure_rates_overall_and_per_day_count_dkim_and_spf_separately():
    day1 = [line_row("1.1.1.1", 90), line_row("2.2.2.2", 10, ok=False, dkim=False, spf=True)]  # fails DKIM only; DMARC passes? no: pass=False here, so DMARC fails
    day3 = [line_row("1.1.1.1", 100)]

    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add_all([rep(acme.id, "acme.com", 100, 90, days_ago=1, rows=day1), rep(acme.id, "acme.com", 100, 100, days_ago=3, rows=day3)])
        await s.commit()
        return await ep.insights(caller(owner), s, days=30, domain="acme.com", client_id=None)

    out = run(body)
    assert out.emails == 200 and out.domain == "acme.com"
    assert (out.rates.dmarc, out.rates.dkim, out.rates.spf) == (5.0, 5.0, 0.0)
    assert [(p.total, p.dmarc_fail, p.dkim_fail, p.spf_fail) for p in out.series] == [(100, 0, 0, 0), (100, 10, 10, 0)]  # oldest day first
    assert out.series[0].day < out.series[1].day


def test_top_senders_are_named_when_known_and_grouped_by_address_when_not_with_a_status():
    rows = [
        line_row("40.1.1.1", 60, spf_domains=["spf.protection.outlook.com"]),
        line_row("40.1.1.2", 40, spf_domains=["spf.protection.outlook.com"]),  # a second address of the same service is one sender
        line_row("9.9.9.9", 5, ok=False),
        line_row("9.9.9.9", 5),
        line_row("8.8.8.8", 3, ok=False),
        line_row("50.1.1.1", 7, dkim_domains=["s1._domainkey.sendgrid.net"], ok=False, dkim=True, spf=False),
    ]

    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add(rep(acme.id, "acme.com", 120, 110, rows=rows))
        await s.commit()
        return await ep.insights(caller(owner), s, days=30, domain=None, client_id=None)

    names = {x.name: x for x in run(body).senders}
    assert names["Microsoft 365"].emails == 100 and names["Microsoft 365"].status == "passing" and names["Microsoft 365"].identified
    assert names["Unknown (9.9.9.9)"].status == "partly" and names["Unknown (9.9.9.9)"].identified is False
    assert names["Unknown (8.8.8.8)"].status == "failing"
    assert names["SendGrid"].failed == 7
    assert [x.emails for x in run(body).senders] == sorted([x.emails for x in run(body).senders], reverse=True)


def test_top_sending_domains_come_from_the_from_address_in_the_report():
    rows = [line_row("1.1.1.1", 5000, header_from="goliveoak.com"), line_row("2.2.2.2", 12, ok=False, header_from="lookalike.example")]

    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(rep(owner.id, "goliveoak.com", 5012, 5000, rows=rows))
        await s.commit()
        return await ep.insights(caller(owner), s, days=30, domain=None, client_id=None)

    domains = {x.domain: x for x in run(body).sending_domains}
    assert domains["goliveoak.com"].emails == 5000 and domains["goliveoak.com"].status == "passing"
    assert domains["lookalike.example"].status == "failing"  # mail claiming to be from a domain that is not the reported one stands out


def test_insights_can_be_narrowed_to_one_client_and_never_include_another_owners_reports():
    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme, birch = await tenant(s, "Acme", owner.id), await tenant(s, "Birch", owner.id)
        theirs = await tenant(s, "Theirs", other.id)
        s.add_all([rep(acme.id, "acme.com", 10, 10, rows=[line_row("1.1.1.1", 10)]), rep(birch.id, "birch.com", 20, 20, rows=[line_row("2.2.2.2", 20)]), rep(theirs.id, "theirs.com", 99, 99, rows=[line_row("3.3.3.3", 99)])])
        await s.commit()
        everyone = await ep.insights(caller(owner), s, days=30, domain=None, client_id=None)
        just_acme = await ep.insights(caller(owner), s, days=30, domain=None, client_id=str(acme.id))
        with pytest.raises(HTTPException) as foreign:
            await ep.insights(caller(owner), s, days=30, domain=None, client_id=str(theirs.id))
        with pytest.raises(HTTPException) as bad_domain:
            await ep.insights(caller(owner), s, days=30, domain="not a domain!", client_id=None)
        with pytest.raises(HTTPException) as bad_id:
            await ep.insights(caller(owner), s, days=30, domain=None, client_id="nope")
        return everyone, just_acme, foreign.value.status_code, bad_domain.value.status_code, bad_id.value.status_code

    everyone, just_acme, foreign, bad_domain, bad_id = run(body)
    assert everyone.emails == 30 and just_acme.emails == 10  # 99 of the other owner's is in neither
    assert (foreign, bad_domain, bad_id) == (404, 422, 422)


def test_insights_with_no_reports_is_empty_not_an_error():
    async def body(s):
        owner = await tenant(s, "Owner")
        await s.commit()
        return await ep.insights(caller(owner), s, days=30, domain=None, client_id=None)

    out = run(body)
    assert (out.emails, out.rates.dmarc, out.series, out.senders, out.sending_domains) == (0, None, [], [], [])
