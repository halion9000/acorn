"""The alerts list for an organization with several clients, against a REAL Postgres as the restricted application role (row-level security on), set up like the devices tests.

It checks what the SQLite tests cannot: that ONE read across the clients (inside the cross-tenant read block) sees exactly the organization and its own clients, never an unrelated tenant or another organization's
client, and that the counts, the collapse of repeats (which must not join two clients' alerts) and the client-name search come out right.
Opt in with AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL (a disposable, fully migrated database).
"""

import json
import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import alerts as alerts_endpoint
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

DEFAULTS = dict(
    page=1,
    page_size=50,
    severity=None,
    status=None,
    category=None,
    assigned_to_me=False,
    search=None,
    min_confidence=None,
    confidence_label=None,
    source=None,
    client_id=None,
    device=None,
    since=None,
    until=None,
    person=None,
    ticket=None,
    collapse=False,
)


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "other_parent", "stranger")}
    owner = create_async_engine(PG_URL)
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = ids["parent"] if key in ("acme", "birch") else (ids["other_parent"] if key == "stranger" else None)
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )
            rows = [
                ("parent", "own alert", "high", ["pc-01"]),
                ("acme", "disk low", "low", ["pc-01"]),
                ("acme", "disk low", "low", ["pc-01"]),  # a repeat of the one above: the same rule about the same machine
                ("birch", "disk low", "low", ["pc-01"]),  # NOT a repeat of Acme's: another client's machine that happens to share a name
                ("birch", "virus found", "critical", ["pc-02"]),
                ("stranger", "secret", "critical", ["pc-09"]),
                ("other_parent", "also secret", "critical", ["pc-10"]),
            ]
            for who, title, severity, hosts in rows:
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, priority, affected_hosts, affected_users, created_at, updated_at) "
                        "values (gen_random_uuid(), :t, :title, :sev, 'new', 50, cast(:h as jsonb), cast('[]' as jsonb), now(), now())"
                    ),
                    {"t": ids[who], "title": title, "sev": severity, "h": json.dumps(hosts)},
                )
        yield ids
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": [str(x) for x in ids.values()]})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": [str(x) for x in ids.values()]})
        await owner.dispose()


async def list_as(tenant_id, **over):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant_id)
            user = SimpleNamespace(tenant_id=tenant_id, user_id=uuid.uuid4())
            return await alerts_endpoint.list_alerts(user, db, **{**DEFAULTS, **over})
    finally:
        await engine.dispose()


async def test_the_organization_sees_its_own_and_its_clients_alerts_and_nobody_elses(world):
    out = await list_as(world["parent"])
    assert sorted(i.title for i in out.items) == ["disk low", "disk low", "disk low", "own alert", "virus found"]
    assert out.total == 5 and out.summary.total == 5 and out.summary.critical == 1 and out.summary.high == 1
    assert {i.client_name.split("-")[0] for i in out.items if i.client_name} == {"acme", "birch"}


async def test_a_client_chosen_gives_only_that_client_and_a_foreign_client_is_not_found(world):
    only = await list_as(world["parent"], client_id=world["acme"])
    assert [i.title for i in only.items] == ["disk low", "disk low"] and only.total == 2
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as e:
        await list_as(world["parent"], client_id=world["stranger"])
    assert e.value.status_code == 404


async def test_the_other_organization_sees_only_its_own(world):
    out = await list_as(world["other_parent"])
    assert sorted(i.title for i in out.items) == ["also secret", "secret"]


async def test_collapsing_repeats_never_joins_two_clients_alerts(world):
    out = await list_as(world["parent"], collapse=True)
    disk = [i for i in out.items if i.title == "disk low"]
    assert len(disk) == 2, "Acme's two are one group and Birch's one is another, though the machine has the same name"
    assert sorted(i.repeat_count for i in disk) == [1, 2]
    assert out.total == 4


async def test_filters_and_the_client_name_search_come_out_right(world):
    critical = await list_as(world["parent"], severity="critical")
    assert [i.title for i in critical.items] == ["virus found"]
    assert critical.summary.total == 5, "the counts above the list ignore the severity filter"
    by_client = await list_as(world["parent"], search="birch")
    assert sorted(i.title for i in by_client.items) == ["disk low", "virus found"], "a client's name matches all that client's alerts"
    by_text = await list_as(world["parent"], search="virus")
    assert [i.title for i in by_text.items] == ["virus found"]


async def test_paging_gives_every_alert_once_in_newest_first_order(world):
    first = await list_as(world["parent"], page=1, page_size=2)
    second = await list_as(world["parent"], page=2, page_size=2)
    third = await list_as(world["parent"], page=3, page_size=2)
    ids = [i.id for i in [*first.items, *second.items, *third.items]]
    assert len(ids) == 5 and len(set(ids)) == 5
