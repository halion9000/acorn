"""The bulk Restore and Close of stale alerts, against a REAL Postgres as the restricted application role (row-level security on).

The route reads AND writes (the alerts and the audit row) inside the cross-tenant read block. A policy that let the block read but not write would make both buttons fail only in production, so this runs
the route's own function as ``aisoc_app``: it must change the organization's and its clients' stale alerts, leave an unrelated organization's alike untouched, and write the audit row.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alert_stale_review as review
from app.db.rls import set_rls_context
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"),
]

REQUEST = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"), state=SimpleNamespace(), url=SimpleNamespace(path="/alert-stale"))


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("parent", "acme", "stranger")}
    actor = uuid.uuid4()
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = ids["parent"] if key == "acme" else None
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            await conn.execute(
                text("insert into users (id, tenant_id, email, username, hashed_password, account_name) values (:i, :t, :e, :u, 'x', :a)"),
                {"i": actor, "t": ids["parent"], "e": f"stale-{tag}@example.test", "u": f"stale{tag}", "a": f"stale-{tag}"},
            )
            for who in ids:
                for title, status in (("quiet", "stale"), ("open", "new")):
                    await conn.execute(
                        text(
                            "insert into alerts (id, tenant_id, title, severity, status, status_before_stale, priority, created_at, updated_at) "
                            "values (gen_random_uuid(), :t, :title, 'low', :st, :before, 50, now() - interval '60 days', now() - interval '60 days')"
                        ),
                        {"t": ids[who], "title": title, "st": status, "before": "triaging" if status == "stale" else None},
                    )
        yield {**ids, "actor": actor}
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            everyone = [str(x) for x in ids.values()]
            await conn.execute(text("alter table audit_log disable trigger user"))
            await conn.execute(text("delete from audit_log where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(text("alter table audit_log enable trigger user"))
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": everyone})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": everyone})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": everyone})
        await owner.dispose()


async def act_as_parent(ids, what, **over):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, ids["parent"])
            user = SimpleNamespace(tenant_id=ids["parent"], user_id=ids["actor"])
            body = review.Selection(confirm=True, **over)
            return await review._act(body, REQUEST, user, db, what)
    finally:
        await engine.dispose()


async def statuses(ids):
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            rows = (await conn.execute(text("select tenant_id, title, status, status_before_stale from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})).all()
        return {(r[0], r[1]): (r[2], r[3]) for r in rows}
    finally:
        await owner.dispose()


async def test_restore_changes_only_the_organizations_own_and_its_clients_stale_alerts(world):
    out = await act_as_parent(world, "restore")
    assert out.changed == 2
    after = await statuses(world)
    for who in ("parent", "acme"):
        assert after[(world[who], "quiet")] == ("triaging", None), "put back exactly as it was"
    assert after[(world["stranger"], "quiet")] == ("stale", "triaging"), "an unrelated organization's alerts are not touched"
    assert after[(world["parent"], "open")][0] == "new"


async def test_close_finishes_the_stale_ones_of_one_client_and_writes_its_audit_row(world):
    out = await act_as_parent(world, "close", client_id=world["acme"])
    assert out.changed == 1
    after = await statuses(world)
    assert after[(world["acme"], "quiet")][0] == "closed"
    assert after[(world["parent"], "quiet")][0] == "stale" and after[(world["stranger"], "quiet")][0] == "stale"
    owner = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with owner.connect() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            n = (await conn.execute(text("select count(*) from audit_log where tenant_id = :t and action = 'alerts:stale_closed'"), {"t": world["parent"]})).scalar_one()
        assert n == 1
    finally:
        await owner.dispose()
