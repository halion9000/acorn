"""One-time policy acceptance links (r7-af-13): the pure rules, and the whole flow against Postgres (make a link, open it, accept once, expiry, revoke)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import policy_links as pl

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def test_tokens_are_random_well_formed_and_only_their_hash_is_kept():
    tokens = {pl.new_token() for _ in range(50)}
    assert len(tokens) == 50 and all(pl.TOKEN_RE.match(t) for t in tokens)
    t = next(iter(tokens))
    assert pl.hash_token(t) == pl.hash_token(t) and pl.hash_token(t) != t and t not in pl.hash_token(t)
    assert len(pl.hash_token(t)) == 64 and pl.hash_token(t) != pl.hash_token(t + "x")
    assert pl.link_path("abc") == "/api/v1/public/policy/abc"
    assert not pl.TOKEN_RE.match("short") and not pl.TOKEN_RE.match("x" * 24 + "/..")


def test_expiry_defaults_to_fourteen_days_and_is_clamped():
    assert pl.expiry(NOW, None) == NOW + timedelta(days=14)
    assert pl.expiry(NOW, 3) == NOW + timedelta(days=3)
    assert pl.expiry(NOW, 0) == NOW + timedelta(days=1)
    assert pl.expiry(NOW, 9999) == NOW + timedelta(days=pl.MAX_DAYS)


def test_a_link_is_open_until_used_or_expired_and_used_wins():
    soon, past = NOW + timedelta(hours=1), NOW - timedelta(seconds=1)
    assert pl.state_of(soon, None, NOW) == "open"
    assert pl.state_of(past, None, NOW) == "expired"
    assert pl.state_of(NOW, None, NOW) == "expired", "the expiry moment itself is already expired"
    assert pl.state_of(soon, NOW, NOW) == "used" and pl.state_of(past, NOW, NOW) == "used"
    assert pl.state_of(datetime(2026, 11, 22), None, NOW) == "open", "a naive time is read as UTC"


def test_the_page_escapes_everything_and_asks_for_a_name_and_a_tick():
    page = pl.render_form("Acme <b>", "<script>alert(1)</script>", 3, "Rule 1 <img src=x onerror=alert(1)>", "p@x.test", "2026-12-01")
    assert "<script>" not in page and "<img" not in page and "<b>" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page and "version 3" in page and "p@x.test" in page
    assert 'name="name"' in page and 'name="agree"' in page and 'method="post"' in page and "noindex" in page


def test_the_form_body_is_parsed_with_a_size_cap_and_first_values():
    assert pl.parse_form(b"name=Ann+Lee&agree=yes") == {"name": "Ann Lee", "agree": "yes"}
    assert pl.parse_form(b"name=a&name=b") == {"name": "a"}
    assert pl.parse_form(b"") == {}
    assert len(pl.parse_form(b"name=" + b"x" * 100000)["name"]) <= 4096


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")


class _Req:
    def __init__(self, body: bytes) -> None:
        self._b = body

    async def body(self) -> bytes:
        return self._b


@pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")
@pytest.mark.asyncio
async def test_a_link_works_once_expires_and_can_be_revoked(monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.api.v1.endpoints import governance as gv
    from app.api.v1.endpoints import public_pages as pp
    from app.db.rls import set_rls_context

    tid, item, tag = uuid.uuid4(), uuid.uuid4(), uuid.uuid4().hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app_engine = create_async_engine(APP_URL, poolclass=NullPool)
    monkeypatch.setattr(pp, "AsyncSessionLocal", async_sessionmaker(app_engine, expire_on_commit=False))
    pp.reset_limits()
    staff = SimpleNamespace(tenant_id=tid, user_id=uuid.uuid4(), email="hal@x.test", role="tenant_admin")
    req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={}, state=SimpleNamespace())

    async def with_db(work):
        async with async_sessionmaker(app_engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            out = await work(db)
            await db.commit()
            return out

    async def gone(token, method):
        with pytest.raises(HTTPException) as e:
            await method(token) if method is pp.public_policy_page else await method(token, _Req(b"name=A&agree=yes"))
        assert e.value.status_code == 404

    try:
        async with owner.begin() as c:
            await c.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": f"Links {tag}", "s": f"pl-{tag}"})
            await c.execute(
                text("insert into users (id, tenant_id, email, account_name, username, hashed_password, role, is_active) values (:u,:t,'hal@x.test',:a,'hal','x','tenant_admin',true)"),
                {"u": staff.user_id, "t": tid, "a": f"hal-{tag}"},
            )
            await c.execute(
                text("insert into governance_items (id, tenant_id, kind, title, owner, notes, interval_days, next_due) values (:i,:t,'policy','Acceptable use','hal','',365,current_date)"),
                {"i": item, "t": tid},
            )
            await c.execute(text("insert into governance_versions (id, tenant_id, item_id, version, body) values (:v,:t,:i,2,'No sharing passwords. <b>Ever.</b>')"), {"v": uuid.uuid4(), "t": tid, "i": item})

        made = await with_db(lambda db: gv.make_accept_links(tid, item, gv.AcceptLinkIn(emails=["Out.Side@X.test", "second@x.test"]), req, staff, db))
        assert [m.email for m in made] == ["out.side@x.test", "second@x.test"] and all(m.version == 2 and m.state == "open" and m.path for m in made)
        assert all(m.url is None and not m.emailed for m in made), "no public address is set, so no whole link and nothing e-mailed"
        token = made[0].path.rsplit("/", 1)[1]

        page = await pp.public_policy_page(token)
        assert page.status_code == 200 and b"No sharing passwords." in page.body and b"&lt;b&gt;Ever.&lt;/b&gt;" in page.body and b"out.side@x.test" in page.body
        assert page.headers["cache-control"] == "no-store" and "form-action 'self'" in page.headers["content-security-policy"]

        # the stored row has the hash, never the token
        async with owner.begin() as c:
            stored = (await c.execute(text("select token_hash from policy_accept_links where tenant_id=:t and email='out.side@x.test'"), {"t": tid})).scalar_one()
        assert stored == pl.hash_token(token) and token not in stored

        # a missing name or tick records nothing and leaves the link open
        refused = await pp.public_policy_accept(token, _Req(b"name=&agree=yes"))
        assert refused.status_code == 422
        refused = await pp.public_policy_accept(token, _Req(b"name=Ann+Lee"))
        assert refused.status_code == 422
        async with owner.begin() as c:
            assert (await c.execute(text("select count(*) from policy_acceptances where tenant_id=:t"), {"t": tid})).scalar_one() == 0

        done = await pp.public_policy_accept(token, _Req(b"name=Ann+Lee&agree=yes"))
        assert done.status_code == 200 and b"recorded" in done.body
        async with owner.begin() as c:
            row = (await c.execute(text("select email, version, display_name, recorded_by from policy_acceptances where tenant_id=:t"), {"t": tid})).one()
        assert tuple(row) == ("out.side@x.test", 2, "Ann Lee", "link")

        # used: the page says so without the policy text, a second post records nothing more
        again = await pp.public_policy_page(token)
        assert b"Already accepted" in again.body and b"No sharing passwords" not in again.body
        second = await pp.public_policy_accept(token, _Req(b"name=Ann+Lee&agree=yes"))
        assert second.status_code == 410
        async with owner.begin() as c:
            assert (await c.execute(text("select count(*) from policy_acceptances where tenant_id=:t"), {"t": tid})).scalar_one() == 1

        # junk and unknown tokens: one 404
        await gone("short", pp.public_policy_page)
        await gone("not-a-real-token-but-the-right-length-xx", pp.public_policy_page)
        await gone("not-a-real-token-but-the-right-length-xx", pp.public_policy_accept)

        # expiry: an old link answers 410 and records nothing
        token2 = made[1].path.rsplit("/", 1)[1]
        async with owner.begin() as c:
            await c.execute(text("update policy_accept_links set expires_at = now() - interval '1 minute' where tenant_id=:t and email='second@x.test'"), {"t": tid})
        assert (await pp.public_policy_page(token2)).status_code == 410
        assert (await pp.public_policy_accept(token2, _Req(b"name=B&agree=yes"))).status_code == 410

        # staff list: states, no links; a new link can be revoked and then stops working
        listed = await with_db(lambda db: gv.list_accept_links(tid, item, staff, db))
        assert {(r.email, r.state) for r in listed} == {("out.side@x.test", "used"), ("second@x.test", "expired")} and all(r.path is None for r in listed)
        third = (await with_db(lambda db: gv.make_accept_links(tid, item, gv.AcceptLinkIn(emails=["third@x.test"], expires_days=3), req, staff, db)))[0]
        token3 = third.path.rsplit("/", 1)[1]
        assert (await pp.public_policy_page(token3)).status_code == 200
        await with_db(lambda db: gv.revoke_accept_link(tid, item, third.id, req, staff, db))
        assert (await pp.public_policy_page(token3)).status_code == 410

        # e-mailing is refused with a reason when no public address is set
        with pytest.raises(HTTPException) as e:
            await with_db(lambda db: gv.make_accept_links(tid, item, gv.AcceptLinkIn(emails=["z@x.test"], send=True), req, staff, db))
        assert e.value.status_code == 422 and "PUBLIC_PAGES_BASE_URL" in e.value.detail
    finally:
        async with owner.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await c.execute(text("set local session_replication_role = replica"))
            for table in ("policy_accept_links", "policy_acceptances", "governance_versions", "governance_items", "audit_log", "users"):
                await c.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tid})
            await c.execute(text("delete from tenants where id = :t"), {"t": tid})
        await owner.dispose()
        await app_engine.dispose()
