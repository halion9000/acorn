"""Migration 174 turns clients:view on for every role that exists, against a REAL Postgres (AISOC_TEST_PG_URL, a disposable fully migrated database).

The permission is new and the people who have roles today must not lose sight of their clients, so the migration grants it to every role, system and custom, in every organisation, and a second run
adds nothing. A role made afterwards starts without it (it is a choice per role).
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]
_FILE = (Path(__file__).resolve().parent.parent / "migrations" / "174_clients_view_permission.sql").read_text(encoding="utf-8")
# The driver takes one statement at a time: the file's statements, without its comment lines.
_CODE = [line for line in _FILE.splitlines() if not line.lstrip().startswith("--")]
STATEMENTS = [part.strip() for part in " ".join(_CODE).split(";") if part.strip()]


async def run_migration(conn):
    for statement in STATEMENTS:
        await conn.exec_driver_sql(statement)


async def test_the_migration_gives_every_role_the_permission_once_and_a_later_role_starts_without_it():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tag = uuid.uuid4().hex[:8]
    tenant, early, late = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, :n, :s)"), {"t": tenant, "n": f"cv-{tag}", "s": f"cv-{tag}"}
            )
            await conn.execute(text("insert into roles (id, tenant_id, name) values (:r, :t, 'vCIO early')"), {"r": early, "t": tenant})
            # The migration was applied when the database was built; take the permission away from everyone to stand where production stood before it.
            await conn.execute(
                text("delete from role_permissions where permission_id = (select id from permissions where name = 'clients:view')")
            )
            await conn.execute(text("delete from permissions where name = 'clients:view'"))
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await run_migration(conn)
        held = text(
            "select count(*) from roles r join role_permissions rp on rp.role_id = r.id join permissions p on p.id = rp.permission_id where p.name = 'clients:view' and r.id = :r"
        )
        total = text("select count(*) from roles")
        holding = text(
            "select count(distinct rp.role_id) from role_permissions rp join permissions p on p.id = rp.permission_id where p.name = 'clients:view'"
        )
        async with engine.connect() as conn:
            assert (await conn.execute(held, {"r": early})).scalar_one() == 1, "a custom role made before the migration holds it"
            assert (await conn.execute(holding)).scalar_one() == (await conn.execute(total)).scalar_one(), "every role holds it"
            assert (
                await conn.execute(text("select count(*) from permissions where name = 'clients:view' and category = 'clients'"))
            ).scalar_one() == 1
        async with engine.begin() as conn:
            await run_migration(conn)  # a second run changes nothing and does not fail
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("insert into roles (id, tenant_id, name) values (:r, :t, 'vCIO late')"), {"r": late, "t": tenant})
        async with engine.connect() as conn:
            assert (await conn.execute(held, {"r": late})).scalar_one() == 0, "a role made afterwards starts without it"
            assert (await conn.execute(holding)).scalar_one() == (await conn.execute(total)).scalar_one() - 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from roles where tenant_id = :t"), {"t": tenant})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tenant})
        await engine.dispose()
