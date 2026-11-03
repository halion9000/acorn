"""Reading the shared DMARC mailbox: the Graph calls it makes, what it keeps, and one whole pass from mailbox to stored report."""

import asyncio
import base64
import contextlib
import gzip
import urllib.parse
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from app.db.database import Base
from app.models.dmarc import DmarcIngestState, DmarcReport
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.models.tenant import Tenant
from app.services import dmarc_mailbox as mb
from app.services import dmarc_store as store
from app.services.alert_email.graph import MailError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BEGIN, END = 1_762_041_600, 1_762_128_000


def xml(domain="client.com", report_id="r1"):
    return (
        f'<?xml version="1.0"?><feedback><report_metadata><org_name>google.com</org_name><email>n@google.com</email><report_id>{report_id}</report_id>'
        f"<date_range><begin>{BEGIN}</begin><end>{END}</end></date_range></report_metadata><policy_published><domain>{domain}</domain><p>none</p></policy_published>"
        "<record><row><source_ip>1.2.3.4</source_ip><count>7</count><policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>pass</spf></policy_evaluated></row>"
        f"<identifiers><header_from>{domain}</header_from></identifiers></record></feedback>"
    ).encode()


def attachment(name, data, kind="#microsoft.graph.fileAttachment"):
    return {"@odata.type": kind, "id": "att-" + name, "name": name, "size": len(data), "contentBytes": base64.b64encode(data).decode()}


def graph(messages, attachments, calls):
    """A stand-in for Microsoft: a token, a list of messages (optionally in pages), and each message's attachments."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append((request.method, url))
        if request.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer tok"
        if "/attachments" in url:
            mid = url.split("/messages/")[1].split("/attachments")[0]
            rest = url.split("/attachments")[1]
            if rest.startswith("/"):  # one attachment by id: the full file, with its contents
                att_id = urllib.parse.unquote(rest[1:].split("?")[0])
                return httpx.Response(200, json=next(a for a in attachments[mid] if a["id"] == att_id))
            # the list: Microsoft refuses contentBytes here (it is on a file attachment only), and the contents are not sent
            if "contentBytes" in url:
                return httpx.Response(400, json={"error": {"message": "Could not find a property named 'contentBytes' on type 'microsoft.graph.attachment'."}})
            return httpx.Response(200, json={"value": [{k: v for k, v in a.items() if k != "contentBytes"} for a in attachments[mid]]})
        if "page2" in url:
            return httpx.Response(200, json={"value": messages[1:]})
        return httpx.Response(200, json={"value": messages[:1] if len(messages) > 1 else messages, **({"@odata.nextLink": "https://graph.test/page2"} if len(messages) > 1 else {})})

    return handler


def reader(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return mb.GraphMailboxReader(tenant_id="t", client_id="c", client_secret="s", sender="dmarc@goliveoak.com", base_url="https://graph.test/v1.0", authority="https://login.test", client=client)


def msg(mid, at="2026-11-02T10:00:00Z"):
    return {"id": mid, "receivedDateTime": at}


def test_it_reads_report_attachments_only_and_skips_everything_else():
    calls = []
    atts = {"m1": [attachment("google.com!client.com!1!2.xml.gz", gzip.compress(xml())), attachment("signature.png", b"png"), attachment("note.txt", b"hi"), attachment("item", b"x", "#microsoft.graph.itemAttachment")]}
    out = asyncio.run(reader(graph([msg("m1")], atts, calls)).new_messages(None))
    assert [m.id for m in out] == ["m1"] and [n for n, _ in out[0].attachments] == ["google.com!client.com!1!2.xml.gz"]
    assert out[0].received == datetime(2026, 11, 2, 10, tzinfo=UTC)
    assert any("hasAttachments" in u for _, u in calls)


def test_it_asks_only_for_what_arrived_after_the_cursor_and_follows_pages():
    calls = []
    atts = {"m1": [], "m2": []}
    since = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
    out = asyncio.run(reader(graph([msg("m1"), msg("m2", "2026-11-02T11:00:00Z")], atts, calls)).new_messages(since))
    assert [m.id for m in out] == ["m1", "m2"]
    listing = next(u for _, u in calls if "mailFolders/inbox/messages" in u)
    assert "receivedDateTime" in listing and "2026-11-01T09%3A30%3A00Z" in listing.replace(":", "%3A")


def test_a_refusal_from_microsoft_is_an_error_with_the_status_not_an_empty_inbox():
    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied", "message": "Access is denied."}})

    with pytest.raises(MailError) as e:
        asyncio.run(reader(handler).new_messages(None))
    assert "403" in str(e.value) and e.value.permanent is True

    def throttled(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(429, json={"error": {"code": "TooManyRequests"}})

    with pytest.raises(MailError) as e2:
        asyncio.run(reader(throttled).new_messages(None))
    assert e2.value.permanent is False


# ── one whole pass ──
class FakeReader:
    def __init__(self, messages=None, error=None):
        self.messages, self.error, self.seen_since = messages or [], error, []

    async def new_messages(self, since):
        self.seen_since.append(since)
        if self.error:
            raise self.error
        return [m for m in self.messages if since is None or m.received > since]


@pytest.fixture(autouse=True)
def no_rls(monkeypatch):
    @contextlib.asynccontextmanager
    async def plain(_db):
        yield

    monkeypatch.setattr(store, "cross_tenant_reads", plain)


def make_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def prepare(engine, factory):
    async with engine.begin() as c:
        await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=[m.__table__ for m in (Tenant, IdentitySource, IdentityMfaUser, DmarcReport, DmarcIngestState)]))
    async with factory() as s:
        owner = Tenant(id=uuid.uuid4(), name="Owner", slug="o-" + uuid.uuid4().hex[:6])
        s.add(owner)
        await s.flush()
        acme = Tenant(id=uuid.uuid4(), name="Acme", slug="a-" + uuid.uuid4().hex[:6], parent_tenant_id=owner.id)
        s.add(acme)
        await s.flush()
        s.add(IdentityMfaUser(tenant_id=acme.id, source="m365", user_id="u1", upn="a@client.com", snapshot_id=uuid.uuid4()))
        await s.commit()
        return owner.id, acme.id


def mailbox(*specs):
    out = []
    for i, (name, data, at) in enumerate(specs):
        out.append(mb.Message(id=f"m{i}", received=datetime.fromisoformat(at), attachments=[(name, data)]))
    return out


def test_a_pass_stores_the_reports_moves_the_cursor_and_a_second_pass_stores_nothing_twice():
    async def go():
        engine, factory = make_factory()
        owner, acme = await prepare(engine, factory)
        r = FakeReader(mailbox(("a.xml", xml(report_id="r1"), "2026-11-02T10:00:00+00:00"), ("b.xml.gz", gzip.compress(xml(report_id="r2")), "2026-11-02T11:00:00+00:00")))
        first = await mb.ingest_once(factory, r, owner, store=store.store_report, now=lambda: datetime(2026, 11, 2, 12, tzinfo=UTC))
        second = await mb.ingest_once(factory, r, owner, store=store.store_report, now=lambda: datetime(2026, 11, 2, 12, 30, tzinfo=UTC))
        async with factory() as s:
            state = (await s.execute(select(DmarcIngestState))).scalar_one()
            reports = (await s.execute(select(DmarcReport))).scalars().all()
        await engine.dispose()
        return first, second, state, reports, r.seen_since, acme

    first, second, state, reports, seen, acme = asyncio.run(go())
    assert (first.stored, first.duplicates, first.rejected, first.messages) == (2, 0, 0, 2)
    assert (second.stored, second.messages) == (0, 0)  # nothing newer than the cursor
    assert seen[0] is None and seen[1] == datetime(2026, 11, 2, 11, tzinfo=UTC)
    assert (state.stored, state.last_error, state.cursor.replace(tzinfo=UTC)) == (2, None, datetime(2026, 11, 2, 11, tzinfo=UTC))
    assert len(reports) == 2 and all(rep.tenant_id == acme and rep.matched for rep in reports)


def test_an_attachment_that_is_not_a_report_is_counted_as_rejected_and_does_not_stop_the_rest():
    async def go():
        engine, factory = make_factory()
        owner, _ = await prepare(engine, factory)
        r = FakeReader(mailbox(("junk.zip", b"PK\x03\x04 not really", "2026-11-02T10:00:00+00:00"), ("ok.xml", xml(report_id="r9"), "2026-11-02T11:00:00+00:00")))
        out = await mb.ingest_once(factory, r, owner, store=store.store_report)
        await engine.dispose()
        return out

    out = asyncio.run(go())
    assert (out.stored, out.rejected) == (1, 1)


def test_a_mailbox_failure_keeps_the_cursor_and_says_why():
    async def go():
        engine, factory = make_factory()
        owner, _ = await prepare(engine, factory)
        ok = FakeReader(mailbox(("a.xml", xml(), "2026-11-02T10:00:00+00:00")))
        await mb.ingest_once(factory, ok, owner, store=store.store_report)
        bad = FakeReader(error=MailError("Microsoft refused the mailbox read: HTTP 403 ErrorAccessDenied", permanent=True))
        out = await mb.ingest_once(factory, bad, owner, store=store.store_report)
        async with factory() as s:
            state = (await s.execute(select(DmarcIngestState))).scalar_one()
        await engine.dispose()
        return out, state

    out, state = asyncio.run(go())
    assert "403" in out.error and (out.stored, out.messages) == (0, 0)
    assert "403" in state.last_error and state.cursor.replace(tzinfo=UTC) == datetime(2026, 11, 2, 10, tzinfo=UTC)


def test_the_reader_uses_its_own_app_when_all_three_are_set_and_the_alert_mail_app_otherwise(monkeypatch):
    from app.workers import dmarc_ingest_worker as w

    s = w.settings
    for name, value in {
        "DMARC_MAILBOX": "lodmarc@goliveoak.com",
        "ALERT_EMAIL_GRAPH_TENANT_ID": "alert-t",
        "ALERT_EMAIL_GRAPH_CLIENT_ID": "alert-c",
        "ALERT_EMAIL_GRAPH_CLIENT_SECRET": "alert-s",
        "DMARC_GRAPH_TENANT_ID": "",
        "DMARC_GRAPH_CLIENT_ID": "",
        "DMARC_GRAPH_CLIENT_SECRET": "",
    }.items():
        monkeypatch.setattr(s, name, value, raising=False)
    fallback = w.make_reader()
    assert (fallback.client_id, fallback.sender) == ("alert-c", "lodmarc@goliveoak.com") and fallback.configured
    monkeypatch.setattr(s, "DMARC_GRAPH_TENANT_ID", "own-t", raising=False)
    assert w.make_reader().client_id == "alert-c"  # two of three is not enough: never a half-and-half mix
    monkeypatch.setattr(s, "DMARC_GRAPH_CLIENT_ID", "own-c", raising=False)
    monkeypatch.setattr(s, "DMARC_GRAPH_CLIENT_SECRET", "own-s", raising=False)
    own = w.make_reader()
    assert (own.tenant_id, own.client_id, own.client_secret) == ("own-t", "own-c", "own-s")


def test_the_listing_filter_starts_with_the_date_the_list_is_sorted_by_or_microsoft_refuses_it():
    """Found live: HTTP 400 InefficientFilter. A list sorted by receivedDateTime is only accepted when the filter's first condition is on receivedDateTime, also on the very first read (no cursor yet)."""
    from urllib.parse import parse_qs, urlsplit

    for since in (None, datetime(2026, 11, 1, 9, 30, tzinfo=UTC)):
        calls = []
        asyncio.run(reader(graph([msg("m1")], {"m1": []}, calls)).new_messages(since))
        listing = next(u for _, u in calls if "mailFolders/inbox/messages" in u)
        query = parse_qs(urlsplit(listing).query)
        assert query["$orderby"] == ["receivedDateTime asc"]
        assert query["$filter"][0].startswith("receivedDateTime gt "), query["$filter"]
        assert query["$filter"][0].endswith("and hasAttachments eq true")
