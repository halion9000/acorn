"""The public trust page: what it shows, what it never shows, and that only a switched-on link opens it."""

import os
import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from app.services import public_trust as pt


def data(**over):
    base = {
        "headline": "Security at Acme",
        "about": "We protect your data.\n\nSecond paragraph.",
        "contact_email": "security@acme.test",
        "documents": [{"name": "SOC 2 report", "url": "https://acme.test/soc2.pdf"}, {"name": "Bad", "url": "javascript:alert(1)"}],
        "frameworks": [{"framework": "SOC2", "controls": 60, "percent_healthy": 82}, {"framework": "HIPAA", "controls": 10, "percent_healthy": None}],
        "policies": [{"title": "Acceptable use", "last_reviewed_at": date(2026, 9, 1)}, {"title": "Backups", "last_reviewed_at": None}],
    }
    return {**base, **over}


def test_the_page_shows_what_was_chosen_and_nothing_else():
    page = pt.render("Acme", data())
    for part in ("Security at Acme", "We protect your data.", "Second paragraph.", "SOC2", "82%", "not measured yet", "Acceptable use", "reviewed 2026-09-01", "SOC 2 report", "security@acme.test"):
        assert part in page, part
    assert "javascript:" not in page and "<script" not in page
    assert 'name="robots" content="noindex,nofollow"' in page


def test_every_value_is_escaped_so_nothing_typed_in_the_settings_can_run_in_a_visitors_browser():
    page = pt.render("Acme <b>", data(headline="<img src=x onerror=alert(1)>", about="<script>alert(1)</script>", contact_email="a@b.c\"><x>", documents=[{"name": "<i>n</i>", "url": "https://x.test/?a=\"b\"&c=<d>"}]))
    assert "<img" not in page and "<script>" not in page and "<i>n</i>" not in page and "<b>" not in page
    assert "&lt;script&gt;" in page and "&lt;img src=x onerror=alert(1)&gt;" in page


def test_a_page_with_nothing_chosen_still_has_a_title_and_the_link_path_and_token_shapes_are_checked():
    page = pt.render("Acme", {})
    assert "Security at Acme" in page and "<h2>" not in page
    tokens = {pt.new_token() for _ in range(50)}
    assert len(tokens) == 50 and all(pt.TOKEN_RE.match(t) for t in tokens)
    assert pt.link_path(None) is None and pt.link_path("abc") == "/api/v1/public/trust/abc"
    assert not pt.TOKEN_RE.match("short") and not pt.TOKEN_RE.match("x" * 24 + "/..") and not pt.TOKEN_RE.match("x" * 65)


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")


@pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database")
@pytest.mark.asyncio
async def test_the_link_is_off_until_switched_on_one_404_for_everything_else_and_a_new_link_replaces_the_old(monkeypatch):
    from app.api.v1.endpoints import public_pages as pp
    from app.api.v1.endpoints import trust_center as tc
    from app.db.rls import set_rls_context
    from fastapi import HTTPException
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    tid, tag = uuid.uuid4(), uuid.uuid4().hex[:8]
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    app_engine = create_async_engine(APP_URL, poolclass=NullPool)
    monkeypatch.setattr(pp, "AsyncSessionLocal", async_sessionmaker(app_engine, expire_on_commit=False))
    pp.reset_limits()
    staff = SimpleNamespace(tenant_id=tid, user_id=uuid.uuid4(), email="hal@x.test", role="tenant_admin")

    async def with_db(work):
        async with async_sessionmaker(app_engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            out = await work(db)
            await db.commit()
            return out

    try:
        async with owner.begin() as c:
            await c.execute(text("insert into tenants (id, name, slug, mssp_role) values (:i, :n, :s, 'parent')"), {"i": tid, "n": f"Pub Trust {tag}", "s": f"pt-{tag}"})
            await c.execute(text("insert into users (id, tenant_id, email, account_name, username, hashed_password, role, is_active) values (:u,:t,'hal@x.test',:a,'hal','x','tenant_admin',true)"), {"u": staff.user_id, "t": tid, "a": f"pt{tag}"})
        await with_db(lambda db: tc.put_trust_center(tc.SettingsIn(enabled=True, headline="Hello from the test", about="About us", contact_email="s@x.test"), tid, db, staff))

        off = await with_db(lambda db: tc.get_trust_center(tid, db, staff))
        assert off.public_enabled is False and off.public_path is None

        on = await with_db(lambda db: tc.put_public_link(tc.PublicLinkIn(enabled=True), tid, db, staff))
        assert on.public_enabled and on.public_path.startswith("/api/v1/public/trust/")
        token = on.public_path.rsplit("/", 1)[1]
        page = await pp.public_trust_page(token)
        assert b"Hello from the test" in page.body and f"Pub Trust {tag}".encode() in page.body
        assert page.headers["cache-control"] == "no-store" and "noindex" in page.headers["x-robots-tag"]

        async def gone(t):
            with pytest.raises(HTTPException) as e:
                await pp.public_trust_page(t)
            assert e.value.status_code == 404

        await gone("not-a-real-token-but-the-right-length-xx")
        await gone("short")
        off_again = await with_db(lambda db: tc.put_public_link(tc.PublicLinkIn(enabled=False), tid, db, staff))
        assert off_again.public_enabled is False and off_again.public_path.endswith(token), "switching off keeps the link"
        await gone(token)  # the same answer as a link that never existed

        again = await with_db(lambda db: tc.put_public_link(tc.PublicLinkIn(enabled=True), tid, db, staff))
        assert again.public_path.endswith(token), "switching back on restores the same link"
        fresh = await with_db(lambda db: tc.put_public_link(tc.PublicLinkIn(enabled=True, new_link=True), tid, db, staff))
        new_token = fresh.public_path.rsplit("/", 1)[1]
        assert new_token != token
        await gone(token)
        assert b"Hello from the test" in (await pp.public_trust_page(new_token)).body
    finally:
        async with owner.begin() as c:
            await c.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await c.execute(text("delete from trust_center_settings where tenant_id = :t"), {"t": tid})
            await c.execute(text("set local session_replication_role = replica"))
            await c.execute(text("delete from audit_log where tenant_id = :t"), {"t": tid})
            await c.execute(text("delete from users where tenant_id = :t"), {"t": tid})
            await c.execute(text("delete from tenants where id = :t"), {"t": tid})
        await owner.dispose()
        await app_engine.dispose()
