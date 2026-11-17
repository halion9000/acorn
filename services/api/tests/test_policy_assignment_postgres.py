"""Assigning policies on a REAL Postgres: assigning (by address and to everyone active), a person seeing and accepting only their own, the reminders (once, again only when due, recorded only when the mail went),
and another owner seeing none of it. Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database, migrations 205 and 207 applied)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import governance as ep
from app.api.v1.endpoints import me_policies as me
from app.api.v1.endpoints.governance import AssignIn, ItemIn, VersionIn
from app.services.alert_email.graph import MailError
from app.workers import policy_reminder_worker as w
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
TODAY = datetime.now(UTC).date()


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    async def noop(*_a, **_k):
        return None

    import app.services.compliance_audit as audit

    monkeypatch.setattr(ep, "emit_audit", noop)
    monkeypatch.setattr(audit, "note", noop)

    async def people(_db, tenant, _client):
        return [
            SimpleNamespace(tenant_id=tenant, email="Ann@x.com", display_name="Ann", licensed=True, kind="user", enabled=True),
            SimpleNamespace(tenant_id=tenant, email="guest@x.com", display_name="G", licensed=True, kind="guest", enabled=True),
            SimpleNamespace(tenant_id=tenant, email="off@x.com", display_name="Off", licensed=True, kind="user", enabled=False),
        ], {}

    import app.api.v1.endpoints.identities as ids

    monkeypatch.setattr(ids, "_people", people)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    a, b = uuid.uuid4(), uuid.uuid4()
    async with factory() as s:
        await off(s)
        for t in (a, b):
            await s.execute(text("insert into tenants (id, name, slug) values (:t, 'x', :s)"), {"t": t, "s": f"pas-{t.hex[:10]}"})
        await s.commit()
    async with factory() as s:
        yield factory, s, a, b
        await off(s)
        for tbl in ("policy_assignments", "policy_acceptances", "governance_versions", "governance_items"):
            await s.execute(text(f"delete from {tbl} where tenant_id in (:a, :b)"), {"a": a, "b": b})
        await s.execute(text("delete from tenants where id in (:a, :b)"), {"a": a, "b": b})
        await s.commit()
    await engine.dispose()


def user(t, email="hal@x.com"):
    return SimpleNamespace(tenant_id=t, user_id=None, email=email)


class FakeMailer:
    configured = True

    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    async def send(self, to, subject, text_):
        if self.fail:
            raise self.fail
        self.sent.append((to, subject, text_))


async def policy(s, a, title="Acceptable use", body="Be nice."):
    await off(s)
    item = await ep.create_item(a, ItemIn(kind="policy", title=title), None, user(a), s)
    await off(s)
    if body:
        await ep.add_version(a, item.id, VersionIn(body=body), None, user(a), s)
        await off(s)
    return item


async def test_assign_by_address_and_to_everyone_active_keeps_the_first_due_day_and_needs_text(world):
    _f, s, a, b = world
    empty = await policy(s, a, "No text", body="")
    with pytest.raises(HTTPException) as e:
        await ep.assign_policy(a, empty.id, AssignIn(emails=["x@x.com"]), None, user(a), s)
    assert e.value.status_code == 422
    await off(s)
    item = await policy(s, a)
    out = await ep.assign_policy(a, item.id, AssignIn(emails=["Bob@x.com", "nope"], everyone=True, due_on=TODAY + timedelta(days=3)), None, user(a), s)
    assert [r.email for r in out] == ["ann@x.com", "bob@x.com"], "guests and disabled accounts are not assigned, bad addresses are dropped"
    await off(s)
    again = await ep.assign_policy(a, item.id, AssignIn(emails=["bob@x.com", "cy@x.com"], due_on=TODAY + timedelta(days=30)), None, user(a), s)
    assert {r.email: r.due_on for r in again}["bob@x.com"] == TODAY + timedelta(days=3), "assigning again keeps the earlier day"
    assert {r.email: r.due_on for r in again}["cy@x.com"] == TODAY + timedelta(days=30)
    await off(s)
    for bad in (AssignIn(emails=["z@x.com"], due_on=TODAY - timedelta(days=1)), AssignIn()):
        with pytest.raises(HTTPException) as e:
            await ep.assign_policy(a, item.id, bad, None, user(a), s)
        assert e.value.status_code == 422
        await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.list_assignments(b, item.id, user(b), s)
    assert e.value.status_code == 404, "another owner cannot see it"


async def test_a_person_sees_and_accepts_only_their_own_and_a_new_version_asks_again(world):
    _f, s, a, b = world
    item = await policy(s, a)
    await ep.assign_policy(a, item.id, AssignIn(emails=["ann@x.com", "bob@x.com"], due_on=TODAY + timedelta(days=5)), None, user(a), s)
    await off(s)
    mine = await me.my_policies(user(a, "ANN@x.com"), s)
    assert [(p.title, p.state, p.version) for p in mine.policies] == [("Acceptable use", "pending", 1)] and mine.to_accept == 1
    assert mine.policies[0].body == "Be nice."
    await off(s)
    nothing = await me.my_policies(user(a, "carl@x.com"), s)
    assert nothing.policies == [] and nothing.to_accept == 0
    await off(s)
    with pytest.raises(HTTPException) as e:
        await me.accept_policy(item.id, user(a, "carl@x.com"), s)
    assert e.value.status_code == 404, "cannot accept what is not assigned to you"
    await off(s)
    done = await me.accept_policy(item.id, user(a, "ann@x.com"), s)
    assert done.state == "accepted" and done.accepted_on == TODAY
    await off(s)
    assert (await me.accept_policy(item.id, user(a, "ann@x.com"), s)).state == "accepted", "twice changes nothing"
    await off(s)
    shown = {r.email: r.state for r in await ep.list_assignments(a, item.id, user(a), s)}
    assert shown == {"ann@x.com": "accepted", "bob@x.com": "pending"}
    await off(s)
    await ep.add_version(a, item.id, VersionIn(body="Be nicer."), None, user(a), s)
    await off(s)
    again = await me.my_policies(user(a, "ann@x.com"), s)
    assert again.policies[0].state == "pending" and again.policies[0].version == 2 and again.policies[0].body == "Be nicer."
    await off(s)
    assert (await me.my_policies(user(b, "ann@x.com"), s)).policies == [], "another owner's people see nothing"


async def test_reminders_go_once_then_only_when_due_and_are_recorded_only_when_the_mail_went(world):
    factory, s, a, b = world
    item = await policy(s, a)
    await ep.assign_policy(a, item.id, AssignIn(emails=["ann@x.com", "bob@x.com"], due_on=TODAY + timedelta(days=5)), None, user(a), s)
    await off(s)
    await me.accept_policy(item.id, user(a, "bob@x.com"), s)
    await off(s)
    broken = FakeMailer(fail=MailError("throttled", permanent=False))
    assert (await w.remind_once(factory=factory, mailer=broken, link="https://c/my-policies"))["failed"] == 1
    mail = FakeMailer()
    first = await w.remind_once(factory=factory, mailer=mail, link="https://c/my-policies")
    assert first == {"sent": 1, "failed": 0} and mail.sent[0][0] == ["ann@x.com"], "the failed try was not recorded, and Bob accepted so gets nothing"
    assert "Acceptable use" in mail.sent[0][2] and "https://c/my-policies" in mail.sent[0][2]
    again = await w.remind_once(factory=factory, mailer=mail)
    assert again["sent"] == 0, "told a moment ago"
    later = await w.remind_once(now=datetime.now(UTC) + timedelta(days=8), factory=factory, mailer=mail)
    assert later["sent"] == 1 and len(mail.sent) == 2
    row = (await ep.list_assignments(a, item.id, user(a), s))
    assert {r.email: r.reminders_sent for r in row} == {"ann@x.com": 2, "bob@x.com": 0}


async def test_without_mail_credentials_nothing_is_sent_and_nothing_is_recorded(world):
    factory, s, a, _b = world
    item = await policy(s, a)
    await ep.assign_policy(a, item.id, AssignIn(emails=["ann@x.com"]), None, user(a), s)
    await off(s)
    unset = FakeMailer()
    unset.configured = False
    assert (await w.remind_once(factory=factory, mailer=unset))["skipped"] == "not_configured"
    assert (await ep.list_assignments(a, item.id, user(a), s))[0].reminders_sent == 0


async def test_unassigning_removes_one_person_and_leaves_what_they_accepted(world):
    _f, s, a, _b = world
    item = await policy(s, a)
    await ep.assign_policy(a, item.id, AssignIn(emails=["ann@x.com", "bob@x.com"]), None, user(a), s)
    await off(s)
    await me.accept_policy(item.id, user(a, "ann@x.com"), s)
    await off(s)
    await ep.unassign_policy(a, item.id, "ANN@x.com", None, user(a), s)
    await off(s)
    assert [r.email for r in await ep.list_assignments(a, item.id, user(a), s)] == ["bob@x.com"]
    await off(s)
    kept = await ep.list_acceptances(a, item.id, user(a), s)
    assert [x.email for x in kept.accepted] == ["ann@x.com"], "the acceptance stays on record"
    await off(s)
    with pytest.raises(HTTPException) as e:
        await ep.unassign_policy(a, item.id, "nobody@x.com", None, user(a), s)
    assert e.value.status_code == 404


