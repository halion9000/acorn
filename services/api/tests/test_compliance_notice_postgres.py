"""The weekly compliance notice on a REAL Postgres (AISOC_TEST_PG_URL, a disposable, fully migrated database; migration 215 applied).

Saving the settings checks the addresses; Send now goes to the e-mail list and the web address and records how it went; the worker sends only what is switched on and due, at most once a week, and nothing when no item is waiting.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance_dashboard as dash
from app.api.v1.endpoints import compliance_notices as ep
from app.services import compliance_notice_sender as sender
from app.workers import compliance_notice_worker as worker
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
NOW = datetime(2026, 11, 18, 9, tzinfo=UTC)


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


class Board:
    """What the Compliance page would list: set ``items`` to change what is waiting."""

    items: list = []


def board_with(items):
    Board.items = items


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    async def noop(**_kw):
        return None

    async def build(_db, tenant):
        return dash.DashboardOut(
            enabled=[],
            health=None,
            by_framework=[],
            risks=dash.RiskLevels(critical=0, high=0, medium=0, low=0, total=0),
            vendors=dash.VendorLevels(critical=0, high=0, medium=0, low=0, unassessed=0, total=0),
            action_items=Board.items,
            generated_at=NOW,
        )

    monkeypatch.setattr(ep, "emit_audit", noop)
    monkeypatch.setattr(dash, "build_dashboard", build)
    Board.items = []

    async def fine(_url):
        return None

    monkeypatch.setattr(sender, "_guard_url", lambda url: None)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": t, "n": f"Org {t.hex[:4]}", "s": f"cn-{t.hex[:10]}"})
        await s.commit()
    async with factory() as s:
        yield factory, s, a, b
        await off(s)
        await s.execute(text("delete from compliance_notices where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def user(email="hal@x.com"):
    return SimpleNamespace(tenant_id=None, user_id=None, email=email)


class FakeMailer:
    configured = True

    def __init__(self):
        self.sent = []

    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))


def an_item(days=-2):
    return dash.ActionItem(kind="vendor_review", name="Acme Hosting", event="annual review", owner="Amy", due=NOW + timedelta(days=days), link="/compliance/vendors")


async def test_saving_checks_the_addresses_and_a_weekly_notice_needs_somewhere_to_go(world):
    _f, s, a, _b = world
    await off(s)
    empty = await ep.get_notice(a, s)
    assert (empty.emails, empty.webhook_url, empty.weekly) == ([], None, False)
    saved = await ep.save_notice(a, ep.NoticeIn(emails=[" Amy@X.com ", "amy@x.com", "nope"], webhook_url="https://hooks.example.com/a", weekly=True), None, user(), s)
    assert (saved.emails, saved.webhook_url, saved.weekly) == (["amy@x.com"], "https://hooks.example.com/a", True)
    await off(s)
    for bad in (ep.NoticeIn(webhook_url="http://hooks.example.com/a"), ep.NoticeIn(weekly=True, emails=["nope"])):
        with pytest.raises(HTTPException) as e:
            await ep.save_notice(a, bad, None, user(), s)
        assert e.value.status_code == 422
        await off(s)
    again = await ep.save_notice(a, ep.NoticeIn(emails=["bob@x.com"], weekly=False), None, user(), s)
    assert again.emails == ["bob@x.com"] and again.webhook_url is None, "saving again replaces what was there"


async def test_send_now_goes_to_the_people_and_the_web_address_and_records_how_it_went(world):
    _f, s, a, _b = world
    await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.send_now(a, None, user(), s)
    assert e.value.status_code == 422, "nothing saved yet"
    await off(s)
    await ep.save_notice(a, ep.NoticeIn(emails=["amy@x.com"], webhook_url="https://hooks.example.com/a"), None, user(), s)
    await off(s)
    board_with([])
    mail, posts = FakeMailer(), []

    async def post(url, payload):
        posts.append((url, payload))
        return SimpleNamespace(status_code=204)

    row = (await s.execute(text("select 1"))).scalar()
    from app.models.governance import ComplianceNotice
    from sqlalchemy import select

    notice = (await s.execute(select(ComplianceNotice).where(ComplianceNotice.tenant_id == a))).scalar_one()
    out = await sender.send_notice(s, notice, now=NOW, mailer=mail, post=post)
    assert out["sent"] is False and out["items"] == 0 and mail.sent == [] and posts == [], "nothing waiting: nothing sent"
    board_with([an_item(-2), an_item(5)])
    out = await sender.send_notice(s, notice, now=NOW, mailer=mail, post=post)
    assert out["sent"] is True and out["email"] == "sent to 1" and out["webhook"] == "sent"
    assert mail.sent[0][0] == ["amy@x.com"] and "2 compliance action items" in mail.sent[0][1]
    assert posts[0][0] == "https://hooks.example.com/a" and posts[0][1]["schema"] == "acorn.compliance_actions.v1" and len(posts[0][1]["items"]) == 2
    assert notice.last_sent_at == NOW and "E-mail: sent to 1" in notice.last_result and row == 1


async def test_a_failed_channel_does_not_stop_the_other_and_nothing_counts_as_sent_when_both_fail(world):
    _f, s, a, _b = world
    from app.models.governance import ComplianceNotice

    await off(s)
    await ep.save_notice(a, ep.NoticeIn(emails=["amy@x.com"], webhook_url="https://hooks.example.com/a"), None, user(), s)
    await off(s)
    from sqlalchemy import select

    notice = (await s.execute(select(ComplianceNotice).where(ComplianceNotice.tenant_id == a))).scalar_one()
    board_with([an_item()])

    async def refused(url, payload):
        return SimpleNamespace(status_code=500)

    unset = FakeMailer()
    unset.configured = False
    out = await sender.send_notice(s, notice, now=NOW, mailer=unset, post=refused)
    assert out["sent"] is False and "credentials are not set" in out["email"] and out["webhook"] == "the address answered 500"
    assert notice.last_sent_at is None, "a notice that went nowhere is tried again"
    good = FakeMailer()
    out = await sender.send_notice(s, notice, now=NOW, mailer=good, post=refused)
    assert out["sent"] is True and out["email"] == "sent to 1" and out["webhook"] == "the address answered 500" and notice.last_sent_at == NOW


async def test_the_worker_sends_only_what_is_on_and_due_once_a_week(world):
    factory, s, a, b = world
    await off(s)
    await ep.save_notice(a, ep.NoticeIn(emails=["amy@x.com"], weekly=True), None, user(), s)
    await off(s)
    await ep.save_notice(b, ep.NoticeIn(emails=["bob@x.com"], weekly=False), None, user(), s)
    await off(s)
    board_with([an_item()])
    mail = FakeMailer()
    first = await worker.notify_once(now=NOW, factory=factory, mailer=mail)
    assert first == {"sent": 1, "failed": 0, "idle": 0} and [m[0] for m in mail.sent] == [["amy@x.com"]], "only the switched-on notice"
    again = await worker.notify_once(now=NOW + timedelta(days=3), factory=factory, mailer=mail)
    assert again == {"sent": 0, "failed": 0, "idle": 0} and len(mail.sent) == 1, "not twice in a week"
    later = await worker.notify_once(now=NOW + timedelta(days=8), factory=factory, mailer=mail)
    assert later["sent"] == 1 and len(mail.sent) == 2
    board_with([])
    idle = await worker.notify_once(now=NOW + timedelta(days=20), factory=factory, mailer=mail)
    assert idle == {"sent": 0, "failed": 0, "idle": 1} and len(mail.sent) == 2, "nothing waiting: nothing sent"
