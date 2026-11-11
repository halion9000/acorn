"""The DMARC pages' data: per-client overview (worst first), one domain's trend and failing sources, mailbox status, and the setup lines."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import dmarc as ep
from app.db.database import Base
from app.models.dmarc import DmarcIngestState, DmarcReport, TlsReport
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.models.tenant import Tenant
from app.services import bimi as bimi_check_module
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, IdentitySource, IdentityMfaUser, DmarcReport, DmarcIngestState, TlsReport)]
NOW = datetime.now(UTC)


class FakeResolver:
    """MX answers by domain; a domain not listed has none. `calls` counts the lookups made."""

    def __init__(self, mx=None, flaky=None, broken=(), txt=None, txt_broken=()):
        self.mx_by_domain, self.flaky, self.broken, self.calls = mx or {}, dict(flaky or {}), set(broken), []
        self.txt_by_name, self.txt_broken = txt or {}, set(txt_broken)

    async def txt(self, name):
        self.calls.append(f"txt:{name}")
        if name in self.txt_broken:
            raise RuntimeError("DNS is down")
        return list(self.txt_by_name.get(name, []))

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
    ep._PUBLISHED_CACHE.clear()

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


async def no_policy_fetch(url):
    raise AssertionError("no MTA-STS record was published, so no policy file should be fetched")


def caller(owner):
    return SimpleNamespace(tenant_id=owner.id)


def test_the_overview_adds_up_each_client_domain_and_lists_the_worst_first():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme, birch = await tenant(s, "Acme", owner.id), await tenant(s, "Birch", owner.id)
        s.add_all(
            [
                rep(acme.id, "acme.com", 100, 99),
                rep(acme.id, "acme.com", 100, 91, days_ago=2, policy="reject"),
                rep(birch.id, "birch.com", 50, 10),
                rep(birch.id, "old.com", 10, 10, days_ago=60),
            ]
        )
        await s.commit()
        return await ep.overview(caller(owner), s, days=30)

    out = run(body)
    assert [d.domain for d in out.domains] == [
        "birch.com",
        "acme.com",
    ]  # birch.com is the worst (20%), the 60-day-old report is outside the window
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
    rows_a = [
        {"ip": "1.2.3.4", "count": 90, "pass": True, "header_from": "acme.com", "envelope_from": "acme.com", "disposition": "none"},
        {
            "ip": "9.9.9.9",
            "count": 6,
            "pass": False,
            "header_from": "acme.com",
            "envelope_from": "evil.example",
            "disposition": "quarantine",
        },
    ]
    rows_b = [
        {
            "ip": "9.9.9.9",
            "count": 4,
            "pass": False,
            "header_from": "acme.com",
            "envelope_from": "evil.example",
            "disposition": "quarantine",
        },
        {"ip": "8.8.8.8", "count": 1, "pass": False, "header_from": "acme.com", "envelope_from": "x.example", "disposition": "none"},
    ]

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
    assert (st.configured, st.mailbox, st.last_error, st.stored, st.rejected) == (
        True,
        "dmarc@goliveoak.com",
        "HTTP 403 ErrorAccessDenied",
        12,
        2,
    )


def test_the_setup_gives_each_client_domain_an_alias_and_the_dns_line_for_your_zone():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme Dental", owner.id)
        s.add_all(
            [
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u1", upn="a@acmedental.com", snapshot_id=uuid.uuid4()),
                IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u2", upn="b@acmedental.com", snapshot_id=uuid.uuid4()),
                IdentitySource(
                    tenant_id=acme.id, vendor="huntress", external_id="x", email="c@gmail.com"
                ),  # a provider domain is not a client's
            ]
        )
        await s.commit()
        return await ep.setup(caller(owner), s, FakeResolver({"acmedental.com": ["mail.acmedental.com"]}))

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
    r = FakeResolver(
        mx={"mail.example": ["mx1.mail.example"], "null.example": [""], "slow.example": ["mx.slow.example"]},
        flaky={"slow.example": 1},
        broken=["down.example"],
    )
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


def line_row(
    ip, count, ok=True, dkim=None, spf=None, disposition="none", reason="", spf_domains=(), dkim_domains=(), header_from="acme.com"
):
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
        line_row(
            "6.6.6.6", 2, ok=False, disposition="quarantine", reason="forwarded"
        ),  # what the receiver did decides: quarantined, not overridden
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
    day1 = [
        line_row("1.1.1.1", 90),
        line_row("2.2.2.2", 10, ok=False, dkim=False, spf=True),
    ]  # fails DKIM only; DMARC passes? no: pass=False here, so DMARC fails
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
        s.add_all(
            [
                rep(acme.id, "acme.com", 10, 10, rows=[line_row("1.1.1.1", 10)]),
                rep(birch.id, "birch.com", 20, 20, rows=[line_row("2.2.2.2", 20)]),
                rep(theirs.id, "theirs.com", 99, 99, rows=[line_row("3.3.3.3", 99)]),
            ]
        )
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


class CountryResolver:
    def __init__(self, by_ip):
        from app.services.ip_country import cymru_name

        self.by_name = {cymru_name(ip): [f"1 | x | {code} | y"] for ip, code in by_ip.items()}
        self.calls = []

    async def txt(self, name):
        self.calls.append(name)
        return self.by_name.get(name, [])


def test_mail_is_grouped_by_the_country_of_the_sending_address_and_what_cannot_be_placed_is_said_so():
    from app.services import ip_country

    ip_country._CACHE.clear()
    rows = [
        line_row("8.8.8.8", 30),
        line_row("8.8.4.4", 10, ok=False),
        line_row("1.1.1.1", 5),
        line_row("10.0.0.5", 4),  # private: never asked about
        line_row("9.9.9.9", 2),  # the lookup does not know it
    ]
    r = CountryResolver({"8.8.8.8": "US", "8.8.4.4": "US", "1.1.1.1": "AU"})

    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(rep(owner.id, "goliveoak.com", 51, 41, rows=rows))
        await s.commit()
        return await ep.countries(caller(owner), s, r, days=30, domain=None, client_id=None)

    out = run(body)
    assert [(c.code, c.emails, c.passed, c.failed) for c in out.countries] == [("US", 40, 30, 10), ("AU", 5, 5, 0)]
    assert (out.emails, out.unknown, out.not_looked_up) == (51, 6, 0)
    # Each country names its busiest sending addresses, busiest first, with how many of their messages failed.
    assert [(a.ip, a.emails, a.failed) for a in out.countries[0].addresses] == [("8.8.8.8", 30, 0), ("8.8.4.4", 10, 10)]
    assert [(a.ip, a.emails, a.failed) for a in out.countries[1].addresses] == [("1.1.1.1", 5, 0)]
    listed = {a.ip for c in out.countries for a in c.addresses}
    assert "10.0.0.5" not in listed and "9.9.9.9" not in listed, "an address that could not be placed is in no country"
    assert len(r.calls) == 4  # the private address was not sent to anyone


def test_only_the_busiest_addresses_are_looked_up_and_the_rest_are_counted_as_not_looked_up(monkeypatch):
    from app.services import ip_country

    ip_country._CACHE.clear()
    monkeypatch.setattr(ep, "MAX_LOOKUPS", 2)
    rows = [line_row("8.8.8.8", 50), line_row("8.8.4.4", 30), line_row("1.1.1.1", 5), line_row("9.9.9.9", 3)]
    r = CountryResolver({"8.8.8.8": "US", "8.8.4.4": "US", "1.1.1.1": "AU"})

    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(rep(owner.id, "goliveoak.com", 88, 88, rows=rows))
        await s.commit()
        return await ep.countries(caller(owner), s, r, days=30, domain=None, client_id=None)

    out = run(body)
    assert [(c.code, c.emails) for c in out.countries] == [("US", 80)]
    assert (out.not_looked_up, out.unknown, out.emails) == (8, 0, 88)
    assert len(r.calls) == 2


def test_countries_never_include_another_owners_mail_and_a_foreign_client_is_refused():
    from app.services import ip_country

    ip_country._CACHE.clear()
    r = CountryResolver({"8.8.8.8": "US", "1.1.1.1": "AU"})

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        theirs = await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                rep(owner.id, "goliveoak.com", 5, 5, rows=[line_row("8.8.8.8", 5)]),
                rep(theirs.id, "theirs.com", 99, 99, rows=[line_row("1.1.1.1", 99)]),
            ]
        )
        await s.commit()
        mine = await ep.countries(caller(owner), s, r, days=30, domain=None, client_id=None)
        with pytest.raises(HTTPException) as foreign:
            await ep.countries(caller(owner), s, r, days=30, domain=None, client_id=str(theirs.id))
        return mine, foreign.value.status_code

    mine, foreign = run(body)
    assert [(c.code, c.emails) for c in mine.countries] == [("US", 5)] and foreign == 404


class DnsResolver:
    """Every record type the posture check asks for, by name; anything not listed does not exist."""

    def __init__(self, txt=None, mx=None):
        self.txt_by, self.mx_by, self.calls = txt or {}, mx or {}, []

    async def txt(self, name):
        self.calls.append(name)
        return self.txt_by.get(name, [])

    async def cname(self, name):
        return []

    async def mx(self, name):
        return self.mx_by.get(name, [])

    async def a(self, name):
        return []


def posture(
    domain="acme.com",
    mx=("mx.acme.com",),
    spf="v=spf1 include:spf.protection.outlook.com -all",
    dmarc="v=DMARC1; p=none; rua=mailto:a@goliveoak.com",
):
    from app.services.domain_posture import check_domain

    r = DnsResolver({domain: [spf] if spf else [], f"_dmarc.{domain}": [dmarc] if dmarc else []}, {domain: list(mx)})
    return run_coro(check_domain(domain, r))


def run_coro(c):
    import asyncio

    return asyncio.run(c)


def test_the_advice_follows_the_policy_and_how_much_mail_passes():
    good = posture()
    adv = ep.report_card_advice
    assert any("start enforcing" in a for a in adv("none", 99.0, 5000, good))
    assert any("Find the failing senders" in a for a in adv("none", 80.0, 5000, good))
    assert any("next step is reject" in a for a in adv("quarantine", 99.8, 5000, good))
    assert any("Real mail may be bouncing" in a for a in adv("reject", 90.0, 5000, good))
    assert any("Fully enforced" in a for a in adv("reject", 99.9, 5000, good))
    assert adv("quarantine", 97.0, 5000, good) == []  # nothing to say is nothing said


def test_too_little_mail_is_never_judged_either_way():
    good = posture()
    for policy in ("none", "quarantine", "reject"):
        out = ep.report_card_advice(policy, 100.0, 40, good)
        assert len(out) == 1 and "too few to judge" in out[0]
    assert "too few to judge" in ep.report_card_advice("none", None, 0, good)[0]


def test_a_domain_with_no_mail_records_is_told_it_should_not_send_and_dns_problems_are_listed():
    nomail = posture(mx=(), dmarc=None, spf=None)
    out = ep.report_card_advice("none", 100.0, 5000, nomail)
    assert "no mail records" in out[0]
    assert len(out) > 1  # and what is missing from its SPF and DMARC records follows


def test_the_card_checks_dns_only_for_a_domain_that_has_reports_and_combines_it_with_the_results():
    resolver = DnsResolver(
        {
            "acme.com": ["v=spf1 include:spf.protection.outlook.com -all"],
            "_dmarc.acme.com": ["v=DMARC1; p=none; rua=mailto:a@goliveoak.com"],
        },
        {"acme.com": ["mx.acme.com"]},
    )

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme, theirs = await tenant(s, "Acme", owner.id), await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                rep(acme.id, "acme.com", 1000, 990, rows=[line_row("1.1.1.1", 1000)]),
                rep(theirs.id, "theirs.com", 5, 5, rows=[line_row("2.2.2.2", 5)]),
            ]
        )
        await s.commit()
        card = await ep.domain_report_card("Acme.com.", caller(owner), s, resolver, no_policy_fetch, days=30)
        before = len(resolver.calls)
        with pytest.raises(HTTPException) as unknown:
            await ep.domain_report_card("theirs.com", caller(owner), s, resolver, no_policy_fetch, days=30)  # another owner's domain
        with pytest.raises(HTTPException) as nothing:
            await ep.domain_report_card("never-reported.example", caller(owner), s, resolver, no_policy_fetch, days=30)
        with pytest.raises(HTTPException) as bad:
            await ep.domain_report_card("not a domain!", caller(owner), s, resolver, no_policy_fetch, days=30)
        return card, before, len(resolver.calls), unknown.value.status_code, nothing.value.status_code, bad.value.status_code

    card, before, after, unknown, nothing, bad = run(body)
    assert (card.domain, card.total, card.pass_rate, card.policy) == ("acme.com", 1000, 99.0, "none")
    assert card.posture.mx == ["mx.acme.com"] and card.posture.dmarc.record.startswith("v=DMARC1")
    assert any("start enforcing" in a for a in card.advice)
    assert (unknown, nothing, bad) == (404, 404, 422) and after == before  # no DNS lookup was made for any of the refused ones


def test_at_risk_lists_every_sender_with_failures_by_failing_volume_even_when_it_is_not_a_top_sender():
    rows = [line_row(f"20.0.0.{i}", 100 + i) for i in range(1, 12)]  # eleven busy, passing senders push the quiet one out of the top ten
    rows += [
        line_row("30.0.0.1", 3, ok=False),
        line_row("30.0.0.2", 9, ok=False, spf_domains=["spf.protection.outlook.com"]),
        line_row("30.0.0.2", 500),
    ]

    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(rep(owner.id, "goliveoak.com", 3000, 2900, rows=rows))
        await s.commit()
        return await ep.insights(caller(owner), s, days=30, domain=None, client_id=None)

    out = run(body)
    assert "Unknown (30.0.0.1)" not in [x.name for x in out.senders]  # not among the top ten by volume
    assert [(x.name, x.failed) for x in out.at_risk] == [("Microsoft 365", 9), ("Unknown (30.0.0.1)", 3)]
    assert all(x.failed > 0 for x in out.at_risk)


def test_lookalikes_are_scanned_only_for_a_domain_in_the_callers_reports_and_mail_capable_ones_come_first():
    from app.services import lookalike

    lookalike._CACHE.clear()
    dns = DnsResolver(txt={}, mx={"acme.co": ["mx.acme.co"]})

    async def a(name):
        dns.calls.append(name)
        return ["1.2.3.4"] if name in {"acme.net", "acme.co"} else []

    dns.a = a

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme, theirs = await tenant(s, "Acme", owner.id), await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                rep(acme.id, "acme.com", 10, 10, rows=[line_row("1.1.1.1", 10)]),
                rep(theirs.id, "theirs.com", 5, 5, rows=[line_row("2.2.2.2", 5)]),
            ]
        )
        await s.commit()
        out = await ep.domain_lookalikes("acme.com", caller(owner), s, dns)
        before = len(dns.calls)
        with pytest.raises(HTTPException) as foreign:
            await ep.domain_lookalikes("theirs.com", caller(owner), s, dns)
        return out, foreign.value.status_code, before, len(dns.calls)

    out, foreign, before, after = run(body)
    assert [(x.domain, x.has_mail) for x in out.found] == [("acme.co", True), ("acme.net", False)]
    assert out.checked > 20 and foreign == 404 and after == before  # the refused domain cost no lookups


def test_the_bimi_check_runs_only_for_a_domain_in_the_callers_reports_and_never_fetches_for_a_refused_one():
    fetched = []

    async def fetch(url):
        fetched.append(url)
        raise bimi_check_module.FetchRefused("The certificate address did not answer.")

    resolver = DnsResolver(
        {
            "default._bimi.acme.com": ["v=BIMI1; l=https://acme.com/l.svg; a=https://acme.com/vmc.pem"],
            "_dmarc.acme.com": ["v=DMARC1; p=reject"],
        }
    )

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme, theirs = await tenant(s, "Acme", owner.id), await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                rep(acme.id, "acme.com", 10, 10, rows=[line_row("1.1.1.1", 10)]),
                rep(theirs.id, "theirs.com", 5, 5, rows=[line_row("2.2.2.2", 5)]),
            ]
        )
        await s.commit()
        out = await ep.domain_bimi("acme.com", caller(owner), s, resolver, fetch)
        with pytest.raises(HTTPException) as foreign:
            await ep.domain_bimi("theirs.com", caller(owner), s, resolver, fetch)
        return out, foreign.value.status_code

    out, foreign = run(body)
    assert out.published and out.dmarc_ready and out.problems == ["The certificate address did not answer."]
    assert fetched == ["https://acme.com/vmc.pem"] and foreign == 404  # nothing was fetched for the other owner's domain


def test_blocklists_count_listed_apart_from_not_checked_and_never_treat_a_refusal_as_clear():
    from app.services import blocklist as bl_module

    asked = []

    async def lookup(name):
        asked.append(name)
        if name == "8.8.8.8.zen.spamhaus.org" or name == "1.1.1.1.zen.spamhaus.org":
            return ["127.0.0.2"] if name.startswith("8.") else ["127.255.255.254"]
        if name.endswith("uceprotect.net"):
            raise bl_module.LookupFailed("timeout")
        return []

    rows = [line_row("8.8.8.8", 40), line_row("1.1.1.1", 20), line_row("10.0.0.9", 99), line_row("2001:db8::1", 50)]

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        theirs = await tenant(s, "Theirs", other.id)
        s.add_all([rep(owner.id, "acme.com", 209, 209, rows=rows), rep(theirs.id, "theirs.com", 5, 5, rows=[line_row("3.3.3.3", 5)])])
        await s.commit()
        out = await ep.domain_blocklists("acme.com", caller(owner), s, lookup, days=30)
        before = len(asked)
        with pytest.raises(HTTPException) as foreign:
            await ep.domain_blocklists("theirs.com", caller(owner), s, lookup, days=30)
        return out, foreign.value.status_code, before, len(asked)

    out, foreign, before, after = run(body)
    assert [a.ip for a in out.addresses] == ["8.8.8.8", "1.1.1.1"]  # private and IPv6 addresses are never asked about; busiest first
    by_ip = {a.ip: {r.list_name: r.status for r in a.results} for a in out.addresses}
    assert by_ip["8.8.8.8"]["Spamhaus ZEN"] == "listed" and by_ip["1.1.1.1"]["Spamhaus ZEN"] == "refused"
    assert by_ip["8.8.8.8"]["UCEPROTECT level 1"] == "no_answer" and by_ip["8.8.8.8"]["SpamCop"] == "clear"
    assert out.listed == 1
    assert out.not_checked == 3  # two UCEPROTECT lookups that failed and one Spamhaus refusal: none of them is "clear"
    assert foreign == 404 and after == before


def test_reputation_combines_registration_with_the_domains_own_mail_and_says_unknown_when_the_record_cannot_be_read():
    import json

    from app.services import safe_fetch as sf

    asked = []

    async def good(url):
        asked.append(url)
        return json.dumps(
            {
                "events": [
                    {"eventAction": "registration", "eventDate": "2010-01-01T00:00:00Z"},
                    {"eventAction": "expiration", "eventDate": "2040-01-01T00:00:00Z"},
                ]
            }
        ).encode()

    async def refused(url):
        raise sf.FetchRefused("The address did not answer.")

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme, theirs = await tenant(s, "Acme", owner.id), await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                rep(acme.id, "acme.com", 1000, 800, policy="quarantine", rows=[line_row("1.1.1.1", 1000)]),
                rep(theirs.id, "theirs.com", 5, 5, rows=[line_row("2.2.2.2", 5)]),
            ]
        )
        await s.commit()
        ok = await ep.domain_reputation("acme.com", caller(owner), s, good, days=30)
        before = len(asked)
        down = await ep.domain_reputation("acme.com", caller(owner), s, refused, days=30)
        with pytest.raises(HTTPException) as foreign:
            await ep.domain_reputation("theirs.com", caller(owner), s, good, days=30)
        return ok, down, foreign.value.status_code, before, len(asked)

    ok, down, foreign, before, after = run(body)
    facts = {f.label: f for f in ok.facts}
    assert facts["Registered"].tone == "good" and facts["Registration ends"].tone == "good"
    assert facts["Its own mail"].tone == "bad" and "80.0%" in facts["Its own mail"].text  # 800 of 1000 pass
    assert facts["DMARC policy"].tone == "good" and asked == ["https://rdap.org/domain/acme.com"]
    assert {f.label: f for f in down.facts}["Registered"].tone == "unknown" and "did not answer" in {f.label: f for f in down.facts}[
        "Registered"
    ].text
    assert foreign == 404 and after == before  # no lookup for another owner's domain


def tls_row(tenant_id, domain, success, failure, failures=(), days_ago=1, matched=True, rid=None):
    from app.models.dmarc import TlsReport

    end = NOW - timedelta(days=days_ago)
    return TlsReport(
        tenant_id=tenant_id,
        matched=matched,
        domain=domain,
        reporter="google.com",
        report_id=rid or uuid.uuid4().hex,
        policy_type="sts",
        begin_at=end - timedelta(days=1),
        end_at=end,
        success=success,
        failure=failure,
        failures=[{"type": t, "count": n} for t, n in failures],
    )


def test_tls_reports_are_summed_per_domain_with_the_worst_first_and_never_include_another_owners():
    from app.models.dmarc import TlsReport  # noqa: F401  (the table exists in the test database below)

    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme, theirs = await tenant(s, "Acme", owner.id), await tenant(s, "Theirs", other.id)
        s.add_all(
            [
                tls_row(acme.id, "acme.com", 90, 10, [("certificate-expired", 6), ("starttls-not-supported", 4)]),
                tls_row(acme.id, "acme.com", 100, 0),
                tls_row(owner.id, "goliveoak.com", 500, 0),
                tls_row(acme.id, "old.example", 1, 99, days_ago=200),  # outside the period
                tls_row(theirs.id, "theirs.com", 1, 1),
            ]
        )
        await s.commit()
        return await ep.tls_overview(caller(owner), s, days=30)

    out = run(body)
    assert [d.domain for d in out.domains] == [
        "acme.com",
        "goliveoak.com",
    ]  # worst first; the old report and the other owner's are left out
    acme_row = out.domains[0]
    assert (acme_row.reports, acme_row.success, acme_row.failure, acme_row.success_rate) == (2, 190, 10, 95.0)
    assert [(f.type, f.count) for f in acme_row.failures] == [("certificate-expired", 6), ("starttls-not-supported", 4)]
    assert out.domains[1].success_rate == 100.0 and out.domains[1].failures == []


def test_the_setup_lists_the_tls_reporting_record_for_each_domain_pointing_at_the_same_alias():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme Dental", owner.id)
        s.add(IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u1", upn="a@acmedental.com", snapshot_id=uuid.uuid4()))
        await s.commit()
        return await ep.setup(caller(owner), s, FakeResolver({"acmedental.com": ["mx.acmedental.com"]}))

    line = run(body).lines[0]
    assert line.tls_rpt_name == "_smtp._tls.acmedental.com"
    assert line.tls_rpt_value == f"v=TLSRPTv1; rua=mailto:{line.alias}"


def test_the_advice_warns_near_the_spf_lookup_limit_and_says_when_it_is_only_a_minimum():
    from app.services.spf_lookups import SpfLookups

    good = posture()
    adv = ep.report_card_advice
    over = adv("none", 99.0, 5000, good, SpfLookups(12, True, True))
    assert any("12 DNS lookups" in a and "receivers stop at 10" in a and "at least" not in a for a in over)
    partial = adv("none", 99.0, 5000, good, SpfLookups(11, False, True))
    assert any("at least 11 DNS lookups" in a for a in partial)
    near = adv("none", 99.0, 5000, good, SpfLookups(9, True, False))
    assert any("9 of the 10 DNS lookups" in a for a in near)
    assert not any("DNS lookups" in a for a in adv("none", 99.0, 5000, good, SpfLookups(5, True, False)))
    assert not any(
        "of the 10 DNS lookups" in a for a in adv("none", 99.0, 5000, good, SpfLookups(9, False, False))
    ), "a partial count under the limit makes no claim"
    assert not any("DNS lookups" in a for a in adv("none", 99.0, 5000, good, None))


def test_the_card_reports_the_spf_lookup_count_through_the_includes_and_none_without_an_spf_record():
    records = {
        "acme.com": ["v=spf1 include:a.example include:b.example -all"],
        "a.example": ["v=spf1 a mx include:c.example -all"],
        "b.example": ["v=spf1 mx -all"],
        "c.example": ["v=spf1 a -all"],
        "_dmarc.acme.com": ["v=DMARC1; p=none; rua=mailto:a@goliveoak.com"],
    }

    async def body(s):
        owner = await tenant(s, "Owner")
        acme, bare = await tenant(s, "Acme", owner.id), await tenant(s, "Bare", owner.id)
        s.add_all(
            [
                rep(acme.id, "acme.com", 1000, 990, rows=[line_row("1.1.1.1", 1000)]),
                rep(bare.id, "bare.example", 1000, 990, rows=[line_row("2.2.2.2", 1000)]),
            ]
        )
        await s.commit()
        full = await ep.domain_report_card(
            "acme.com", caller(owner), s, DnsResolver(records, {"acme.com": ["mx.acme.com"]}), no_policy_fetch, days=30
        )
        none = await ep.domain_report_card("bare.example", caller(owner), s, DnsResolver({}, {}), no_policy_fetch, days=30)
        return full, none

    full, none = run(body)
    assert (full.spf_lookups, full.spf_lookups_complete) == (2 + 3 + 1 + 1, True)  # two includes, then a+mx+include, mx, and c's a
    assert (none.spf_lookups, none.spf_lookups_complete) == (None, True)


def test_the_card_carries_the_mta_sts_result_and_its_advice_with_the_real_mail_servers():
    # The published policy lists one mail server; the domain's real MX is another: enforced, so senders would refuse to deliver.
    async def policy(url):
        assert url == "https://mta-sts.acme.com/.well-known/mta-sts.txt"
        return "\n".join(["version: STSv1", "mode: enforce", "mx: other.example.net", "max_age: 604800", ""]).encode()

    records = {"acme.com": ["v=spf1 -all"], "_mta-sts.acme.com": ["v=STSv1; id=1"]}

    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        s.add(rep(acme.id, "acme.com", 1000, 990, rows=[line_row("1.1.1.1", 1000)]))
        await s.commit()
        return await ep.domain_report_card(
            "acme.com", caller(owner), s, DnsResolver(records, {"acme.com": ["mx.acme.com"]}), policy, days=30
        )

    card = run(body)
    assert card.mta_sts.state == "ok" and card.mta_sts.mode == "enforce" and card.mta_sts.uncovered_mx == ["mx.acme.com"]
    assert any("mx.acme.com" in line and "refuse to deliver" in line for line in card.advice)


# ---- is what the Setup tab asks you to publish actually published? ----

ALIAS = "acme-dental.dmarc@goliveoak.com"
AUTH_NAME = "acmedental.com._report._dmarc.goliveoak.com"


def test_the_two_records_are_recognised_whatever_the_spacing_and_case():
    assert ep.rua_names_alias([f"v=DMARC1; p=none; rua=mailto:{ALIAS}"], ALIAS)
    assert ep.rua_names_alias([f"v=DMARC1;p=none;RUA=MAILTO:{ALIAS.upper()}"], ALIAS)
    assert ep.rua_names_alias(["v=DMARC1; p=none", f"v=DMARC1; rua=mailto:x@y.example,mailto:{ALIAS}"], ALIAS), "one of several addresses"
    assert not ep.rua_names_alias(["v=DMARC1; p=none; rua=mailto:someone@else.example"], ALIAS)
    assert not ep.rua_names_alias([f"v=spf1 -all rua=mailto:{ALIAS}"], ALIAS), "it has to be a DMARC record"
    assert not ep.rua_names_alias([], ALIAS)
    assert ep.is_authorization(["v=DMARC1"]) and ep.is_authorization([" v=dmarc1 "])
    assert not ep.is_authorization([]) and not ep.is_authorization(["v=spf1 -all"])


def _setup_with(resolver):
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme Dental", owner.id)
        s.add(IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u1", upn="a@acmedental.com", snapshot_id=uuid.uuid4()))
        await s.commit()
        return await ep.setup(caller(owner), s, resolver)

    return run(body)


def test_the_setup_says_which_records_are_published_and_when_it_looked():
    both = FakeResolver(
        {"acmedental.com": ["mx"]}, txt={"_dmarc.acmedental.com": [f"v=DMARC1; p=none; rua=mailto:{ALIAS}"], AUTH_NAME: ["v=DMARC1"]}
    )
    out = _setup_with(both)
    (line,) = out.lines
    assert (line.rua_published, line.authorization_published) == (True, True) and out.checked_at
    ep._PUBLISHED_CACHE.clear()
    none = _setup_with(FakeResolver({"acmedental.com": ["mx"]}))
    assert (none.lines[0].rua_published, none.lines[0].authorization_published) == (False, False), "nothing seen in DNS yet"
    ep._PUBLISHED_CACHE.clear()
    wrong = _setup_with(
        FakeResolver(
            {"acmedental.com": ["mx"]},
            txt={"_dmarc.acmedental.com": ["v=DMARC1; p=none; rua=mailto:other@else.example"], AUTH_NAME: ["v=DMARC1"]},
        )
    )
    assert (wrong.lines[0].rua_published, wrong.lines[0].authorization_published) == (
        False,
        True,
    ), "a record that names someone else's address does not count"


def test_a_failed_lookup_is_unknown_not_unpublished_and_an_empty_answer_is_asked_twice():
    out = _setup_with(FakeResolver({"acmedental.com": ["mx"]}, txt_broken={"_dmarc.acmedental.com", AUTH_NAME}))
    assert (out.lines[0].rua_published, out.lines[0].authorization_published) == (None, None)
    ep._PUBLISHED_CACHE.clear()
    resolver = FakeResolver({"acmedental.com": ["mx"]})
    _setup_with(resolver)
    assert resolver.calls.count("txt:_dmarc.acmedental.com") == 2, "an empty answer is asked again once before it is called missing"


def test_a_domain_with_no_mail_is_not_looked_up_and_answers_are_kept_for_a_few_minutes():
    out = _setup_with(FakeResolver({}))
    assert (out.lines[0].has_mx, out.lines[0].rua_published, out.lines[0].authorization_published) == (False, None, None)
    ep._PUBLISHED_CACHE.clear()
    resolver = FakeResolver(
        {"acmedental.com": ["mx"]}, txt={"_dmarc.acmedental.com": [f"v=DMARC1; rua=mailto:{ALIAS}"], AUTH_NAME: ["v=DMARC1"]}
    )
    _setup_with(resolver)
    first = len(resolver.calls)
    _setup_with(resolver)
    assert len([c for c in resolver.calls[first:] if c.startswith("txt:")]) == 0, "the second page load used the kept answers"


def test_a_country_lists_at_most_five_addresses_the_busiest_ones():
    from app.services import ip_country

    ip_country._CACHE.clear()
    rows = [line_row(f"8.8.8.{i}", 10 + i) for i in range(1, 9)]
    r = CountryResolver({f"8.8.8.{i}": "US" for i in range(1, 9)})

    async def body(s):
        owner = await tenant(s, "Owner")
        s.add(rep(owner.id, "goliveoak.com", sum(10 + i for i in range(1, 9)), sum(10 + i for i in range(1, 9)), rows=rows))
        await s.commit()
        return await ep.countries(caller(owner), s, r, days=30, domain=None, client_id=None)

    (us,) = run(body).countries
    assert [a.ip for a in us.addresses] == ["8.8.8.8", "8.8.8.7", "8.8.8.6", "8.8.8.5", "8.8.8.4"]
    assert us.emails == sum(10 + i for i in range(1, 9)), "the country total still counts every address, not only the five listed"
