"""A toolbox request against a REAL Postgres as the restricted role: it becomes a pending approval naming the client and every value, never runs, never auto-approves, and a client that is not the caller's is
refused (opt in with AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import toolbox as ep
from app.db.rls import set_rls_context
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
pytestmark = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    owner, acme, stranger = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'owner', :s)"), {"i": owner, "s": f"to-{tag}"})
            await conn.execute(text("insert into tenants (id, name, slug, parent_tenant_id) values (:i, 'Acme', :s, :p)"), {"i": acme, "s": f"ta-{tag}", "p": owner})
            await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'Stranger', :s)"), {"i": stranger, "s": f"ts-{tag}"})
        yield SimpleNamespace(owner=owner, acme=acme, stranger=stranger)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from agent_approvals where tenant_id = :t"), {"t": owner})
            await conn.execute(text("delete from vendor_actions where tenant_id = :t"), {"t": owner})
            await conn.execute(text("alter table audit_log disable trigger user"))
            await conn.execute(text("delete from audit_log where tenant_id = :t"), {"t": owner})
            await conn.execute(text("alter table audit_log enable trigger user"))
            await conn.execute(text("delete from tenants where parent_tenant_id = :t"), {"t": owner})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(owner), str(stranger)]})
        await engine.dispose()


async def call(w, client, tool, args):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="tech@liveoakit.com")
            return await ep.make_request(ep.RequestIn(tool=tool, client_id=client, args=args), user, db)
    finally:
        await engine.dispose()


async def approvals(w):
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text("select status, risk_level, requested_by, title, action from agent_approvals where tenant_id = :t"), {"t": w.owner})).all()
    finally:
        await engine.dispose()


async def test_a_press_creates_one_pending_approval_with_every_value_and_runs_nothing(world):
    out = await call(world, world.acme, "reset_mfa", {"user": "ann@acme.com", "reason": "lost phone"})
    assert out["status"] == "pending" and out["risk"] == "high" and "Nothing has been run" in out["note"]
    rows = await approvals(world)
    assert len(rows) == 1
    status, risk, by, title, action = rows[0]
    assert (status, risk, by, title) == ("pending", "high", "toolbox:tech@liveoakit.com", "Reset a person's MFA: ann@acme.com")
    assert action == {"kind": "toolbox", "tool": "reset_mfa", "client_id": str(world.acme), "client": "Acme", "args": {"user": "ann@acme.com", "reason": "lost phone"}, "secret_args": []}


async def test_a_bad_request_or_a_foreign_client_creates_nothing(world):
    with pytest.raises(HTTPException) as e:
        await call(world, world.acme, "reset_mfa", {"user": "ann@acme.com"})
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e2:
        await call(world, world.stranger, "reset_mfa", {"user": "a@b.co", "reason": "x"})
    assert e2.value.status_code == 404
    assert await approvals(world) == []


async def lookups_for(w, client):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            user = SimpleNamespace(tenant_id=w.owner, user_id=None, email="tech@liveoakit.com")
            return await ep.lookups(client, user, db)
    finally:
        await engine.dispose()


async def put_users(w, client, rows):
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for upn, name, kind in rows:
                await conn.execute(
                    text(
                        "insert into identity_mfa_users (tenant_id, source, user_id, upn, display_name, enabled, user_type, admin, licensed, registered, capable, ca_enforced, security_defaults, snapshot_id)"
                        " values (:t, 'cipp', :u, :upn, :n, true, :k, false, false, false, false, false, false, :s)"
                    ),
                    {"t": client, "u": upn, "upn": upn, "n": name, "k": kind, "s": uuid.uuid4()},
                )
    finally:
        await engine.dispose()


async def test_the_pickers_hold_only_the_chosen_clients_own_people_and_a_foreign_client_is_refused(world):
    await put_users(world, world.acme, [("ann@acme.com", "Ann", "Member"), ("bob@acme.com", "Bob", "Member")])
    await put_users(world, world.stranger, [("spy@stranger.com", "Spy", "Member")])
    out = await lookups_for(world, world.acme)
    assert [p["email"] for p in out["people"]] == ["ann@acme.com", "bob@acme.com"] and out["domains"] == ["acme.com"]
    with pytest.raises(HTTPException) as e:
        await lookups_for(world, world.stranger)
    assert e.value.status_code == 404


def _user(w):
    return SimpleNamespace(tenant_id=w.owner, user_id=None, email="tech@liveoakit.com")


async def with_db(w, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, w.owner)
            return await work(db)
    finally:
        await engine.dispose()


async def queued(w):
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            return (await conn.execute(text("select action, params, status, vendor, tenant_id from vendor_actions where tenant_id = :t order by created_at"), {"t": w.owner})).all()
    finally:
        await engine.dispose()


async def test_the_group_request_asks_core_for_the_clients_most_used_domain_once_and_refuses_a_foreign_or_empty_client(world):
    w = world
    await put_users(w, w.acme, [("ann@acme.com", "Ann", "Member"), ("bob@acme.com", "Bob", "Member"), ("cy@acme.net", "Cy", "Member")])
    first = await with_db(w, lambda db: ep.ask_groups(ep.GroupsIn(client_id=w.acme), _user(w), db))
    assert first["status"] == "waiting" and first["kind"] == "groups"
    again = await with_db(w, lambda db: ep.ask_groups(ep.GroupsIn(client_id=w.acme), _user(w), db))
    assert again["request_id"] == first["request_id"], "a repeat within half an hour reuses the request"
    rows = await queued(w)
    assert len(rows) == 1 and rows[0][:4] == ("directory_lookup", {"domain": "acme.com"}, "pending", "core") and rows[0][4] == w.owner
    with pytest.raises(HTTPException) as e:
        await with_db(w, lambda db: ep.ask_groups(ep.GroupsIn(client_id=w.stranger), _user(w), db))
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e2:
        await with_db(w, lambda db: ep.ask_groups(ep.GroupsIn(client_id=w.acme if False else uuid.uuid4()), _user(w), db))
    assert e2.value.status_code == 404
    assert len(await queued(w)) == 1


async def test_the_answer_is_waiting_then_the_groups_and_a_rules_id_cannot_be_read_as_groups(world):
    w = world
    await put_users(w, w.acme, [("ann@acme.com", "Ann", "Member")])
    first = await with_db(w, lambda db: ep.ask_groups(ep.GroupsIn(client_id=w.acme), _user(w), db))
    rid = uuid.UUID(first["request_id"])
    assert (await with_db(w, lambda db: ep.read_groups(rid, _user(w), db)))["status"] == "waiting"
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(
                text("update vendor_actions set status = 'done', result_message = 'ok', result_data = cast(:d as jsonb) where id = :i"),
                {"d": '{"groups": [{"name": "Sales", "kind": "Security", "mail": null}], "licenses": []}', "i": rid},
            )
    finally:
        await engine.dispose()
    done = await with_db(w, lambda db: ep.read_groups(rid, _user(w), db))
    assert done["status"] == "done" and done["result"]["groups"][0]["name"] == "Sales"
    with pytest.raises(HTTPException) as e:
        await with_db(w, lambda db: ep.read_inbox_rules(rid, _user(w), db))
    assert e.value.status_code == 404, "a groups request is not a rules request"


async def test_inbox_rules_are_asked_only_for_a_person_of_that_client(world):
    w = world
    await put_users(w, w.acme, [("ann@acme.com", "Ann", "Member")])
    await put_users(w, w.stranger, [("spy@stranger.com", "Spy", "Member")])
    with pytest.raises(HTTPException) as e:
        await with_db(w, lambda db: ep.ask_inbox_rules(ep.RulesIn(client_id=w.acme, user="spy@stranger.com"), _user(w), db))
    assert e.value.status_code == 422
    got = await with_db(w, lambda db: ep.ask_inbox_rules(ep.RulesIn(client_id=w.acme, user="Ann@Acme.com"), _user(w), db))
    assert got["status"] == "waiting" and got["kind"] == "rules"
    rows = await queued(w)
    assert [(r[0], r[1]) for r in rows] == [("mailbox_rules_lookup", {"upn": "ann@acme.com"})]


async def test_a_typed_password_is_stored_encrypted_named_as_a_secret_and_never_in_the_summary_or_the_audit(world):
    from app.security.credential_vault import get_vault

    out = await call(world, world.acme, "change_password", {"user": "ann@acme.com", "password": "Correct-Horse-9", "ticket": "4711"})
    assert out["status"] == "pending"
    engine = create_async_engine(PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            row = (await conn.execute(text("select summary, action from agent_approvals where tenant_id = :t"), {"t": world.owner})).one()
            audit = (await conn.execute(text("select changes::text from audit_log where tenant_id = :t"), {"t": world.owner})).scalars().all()
    finally:
        await engine.dispose()
    summary, action = row
    assert "Correct-Horse-9" not in summary and "Password: set (hidden)" in summary
    assert action["secret_args"] == ["password"] and action["args"]["password"] != "Correct-Horse-9"
    assert get_vault().decrypt(action["args"]["password"]) == "Correct-Horse-9", "kept so a later run can use it"
    assert action["args"]["ticket"] == "4711" and action["args"]["require_change"] == "Yes"
    assert not any("Correct-Horse-9" in str(c) for c in audit)
