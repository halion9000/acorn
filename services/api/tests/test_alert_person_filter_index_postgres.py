"""The alert list's person and device filters use an index (migration 127), not a read of every alert.

Opt in with AISOC_TEST_PG_URL (a disposable, fully migrated database). The planner is told to avoid sequential scans, so the plan can only avoid an index scan on the trigram index if the filter's expression does not match it: a change to the query that
stops matching the index fails here. The statement is the filter ``list_alerts`` builds, compiled by SQLAlchemy.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from app.models.alert import Alert
from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


def _like(name: str) -> str:
    # The pattern list_alerts builds: the JSON-quoted lower-case name, with LIKE's own characters escaped.
    return "%" + json.dumps(name.lower(), ensure_ascii=False).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def _plan(statement) -> str:
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local enable_seqscan = off"))
            rows = (await conn.execute(text(f"explain {sql}"))).scalars().all()
        return "\n".join(rows)
    finally:
        await engine.dispose()


async def test_the_person_filter_uses_the_trigram_index():
    stmt = select(Alert.id).where(func.lower(cast(Alert.affected_users, Text)).like(_like("Amy@Acme.com"), escape="\\"))
    plan = await _plan(stmt)
    assert "ix_alerts_affected_users_trgm" in plan, plan


async def test_the_device_filter_uses_the_trigram_index():
    stmt = select(Alert.id).where(func.lower(cast(Alert.affected_hosts, Text)).like(_like("PC-01"), escape="\\"))
    plan = await _plan(stmt)
    assert "ix_alerts_affected_hosts_trgm" in plan, plan


async def test_the_indexed_filter_still_finds_the_right_alerts():
    """An index must not change the answer: exact quoted name, any case, and not a part of an address."""
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant = uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, 'idx-test', :s)"), {"t": tenant, "s": f"idx-{tenant.hex[:10]}"}
            )
            for title, users in (("a", ["Amy@Acme.com"]), ("b", ["amy@acme.com.au"]), ("c", ["bob@acme.com", "AMY@ACME.COM"])):
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, priority, affected_users, created_at, updated_at) "
                        "values (:i, :t, :title, 'low', 'new', 50, cast(:u as jsonb), now(), now())"
                    ),
                    {"i": uuid.uuid4(), "t": tenant, "title": title, "u": json.dumps(users)},
                )
            found = (
                (
                    await conn.execute(
                        select(Alert.title).where(
                            Alert.tenant_id == tenant, func.lower(cast(Alert.affected_users, Text)).like(_like("amy@acme.com"), escape="\\")
                        )
                    )
                )
                .scalars()
                .all()
            )
            await conn.execute(text("delete from alerts where tenant_id = :t"), {"t": tenant})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tenant})
        assert sorted(found) == ["a", "c"]
    finally:
        await engine.dispose()
