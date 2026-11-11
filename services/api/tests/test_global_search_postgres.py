"""Search-everything on a REAL Postgres (AISOC_TEST_PG_URL, a DISPOSABLE fully migrated database): what is found, and that nobody finds another organisation's records."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import global_search as ep
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def world():
    """Live Oak with two clients, and a stranger MSP with a client of its own. Each has an alert, a case, a device and a stock item carrying the word 'router'."""
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    ids = SimpleNamespace(owner=uuid.uuid4(), acme=uuid.uuid4(), birch=uuid.uuid4(), stranger=uuid.uuid4(), theirs=uuid.uuid4())
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, name, parent in (
            (ids.owner, "Live Oak", None),
            (ids.acme, "Waterloo Sparkling Water Corp.", ids.owner),
            (ids.birch, "Birch Law", ids.owner),
            (ids.stranger, "Other MSP", None),
            (ids.theirs, "Their Waterloo Client", ids.stranger),
        ):
            await conn.execute(
                text("insert into tenants (id, name, slug, parent_tenant_id) values (:t, :n, :s, :p)"),
                {"t": tid, "n": name, "s": f"gs-{tag}-{str(tid)[:6]}", "p": parent},
            )
            await conn.execute(
                text(
                    "insert into alerts (id, tenant_id, title, severity, status, event_time, first_seen, last_seen, created_at) values (:i, :t, :ti, 'high', 'new', :n, :n, :n, :n)"
                ),
                {"i": uuid.uuid4(), "t": tid, "ti": f"Router login from new country at {name}", "n": now},
            )
            await conn.execute(
                text(
                    "insert into cases (id, tenant_id, case_number, title, status, severity, created_at) values (:i, :t, :c, :ti, 'open', 'medium', :n)"
                ),
                {"i": uuid.uuid4(), "t": tid, "c": f"C-{tag}-{str(tid)[:4]}", "ti": f"Replace router for {name}", "n": now},
            )
            await conn.execute(
                text("insert into devices (id, tenant_id, hostname, serial_number, last_seen) values (:i, :t, :h, :s, :n)"),
                {"i": uuid.uuid4(), "t": tid, "h": f"ROUTER-{str(tid)[:4]}", "s": f"SN{str(tid)[:6]}", "n": now},
            )
            await conn.execute(
                text(
                    "insert into inventory_items (id, tenant_id, kind, name, quantity, status) values (:i, :t, 'stock', :nm, 1, 'checked_in')"
                ),
                {"i": uuid.uuid4(), "t": tid, "nm": f"Spare router {str(tid)[:4]}"},
            )
            for source in ("microsoft", "google"):
                await conn.execute(
                    text(
                        "insert into identity_mfa_users (tenant_id, source, user_id, upn, display_name, enabled, admin, licensed, registered, capable, ca_enforced, security_defaults, snapshot_id, refreshed_at) "
                        "values (:t, :src, :u, :upn, :dn, true, false, true, true, true, false, false, :snap, :n)"
                    ),
                    {
                        "t": tid,
                        "src": source,
                        "u": f"{source}-{str(tid)[:6]}",
                        "upn": f"jane.doe@{str(tid)[:6]}.example",
                        "dn": "Jane Doe",
                        "snap": uuid.uuid4(),
                        "n": now,
                    },
                )
    return engine, SimpleNamespace(tenant_id=ids.owner, email="hal@goliveoak.com"), ids


async def cleanup(engine, ids):
    every = [ids.owner, ids.acme, ids.birch, ids.stranger, ids.theirs]
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in ("alerts", "cases", "devices", "inventory_items", "identity_mfa_users"):
            await conn.execute(text(f"delete from {table} where tenant_id = any(:t)"), {"t": every})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": every})
    await engine.dispose()


def run(user, db, q, limit=5):
    return ep.search(user, db, q=q, limit=limit)


async def test_a_word_finds_each_kind_for_the_owner_and_its_clients_and_never_the_strangers():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            out = await run(user, db, "router")
            kinds = {h.kind for h in out.hits}
            assert kinds == {"alert", "case", "device", "stock"}
            clients = {h.client for h in out.hits}
            assert clients <= {None, "Waterloo Sparkling Water Corp.", "Birch Law"}, "only Live Oak's own and its clients' records"
            assert not any(str(w.stranger) in (h.client_id or "") or str(w.theirs) in (h.client_id or "") for h in out.hits)
            assert not any("Other MSP" in h.title or "Their Waterloo Client" in h.title for h in out.hits)
            assert len([h for h in out.hits if h.kind == "alert"]) == 3, "Live Oak's own plus its two clients"
    finally:
        await cleanup(engine, w)


async def test_a_clients_name_finds_the_client_and_its_records_but_not_a_strangers_client_with_a_similar_name():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            out = await run(user, db, "waterloo sparkling")
            assert [h.title for h in out.hits if h.kind == "client"] == ["Waterloo Sparkling Water Corp."]
            assert {h.kind for h in out.hits} >= {"client", "alert", "case", "device", "stock"}
            assert all(h.client == "Waterloo Sparkling Water Corp." for h in out.hits), "everything found belongs to that client"
            other = await run(user, db, "waterloo")
            assert str(w.theirs) not in {h.client_id for h in other.hits}
    finally:
        await cleanup(engine, w)


async def test_a_client_user_sees_only_its_own_records():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            as_client = SimpleNamespace(tenant_id=w.acme, email="x@acme.example")
            out = await run(as_client, db, "router")
            assert {h.client for h in out.hits} <= {None}, "its own records, with no client label"
            assert len(out.hits) == 4
    finally:
        await cleanup(engine, w)


async def test_short_questions_find_nothing_and_a_percent_sign_is_not_a_wildcard():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            assert (await run(user, db, "r")).hits == []
            assert (await run(user, db, "  ")).hits == []
            assert (await run(user, db, "%%")).hits == []
            assert (await run(user, db, "ro_ter")).hits == [], "an underscore matches an underscore, not any character"
            assert len([h for h in (await run(user, db, "router", limit=1)).hits if h.kind == "alert"]) == 1
    finally:
        await cleanup(engine, w)


async def test_a_name_or_an_email_finds_the_person_once_and_only_inside_the_callers_own_organisation():
    engine, user, w = await world()
    try:
        async with AsyncSession(engine) as db:
            by_name = await run(user, db, "jane doe")
            people = [h for h in by_name.hits if h.kind == "person"]
            assert len(people) == 3, "Live Oak's own and its two clients: listed by two tools each, shown once"
            assert {h.title for h in people} == {"Jane Doe"}
            assert all(h.detail and h.detail.startswith("jane.doe@") for h in people)
            assert str(w.theirs) not in {h.client_id for h in people}
            by_mail = await run(user, db, f"jane.doe@{str(w.acme)[:6]}")
            assert [h.client_id for h in by_mail.hits if h.kind == "person"] == [str(w.acme)]
            as_client = await run(SimpleNamespace(tenant_id=w.acme, email="x@acme.example"), db, "jane")
            assert len([h for h in as_client.hits if h.kind == "person"]) == 1
            assert [h.kind for h in (await run(user, db, "jane", limit=2)).hits].count("person") == 2
    finally:
        await cleanup(engine, w)
