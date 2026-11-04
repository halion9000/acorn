"""Platform health says how many migrations are recorded and which is the newest, and says nothing rather than guessing when it cannot read them."""

import asyncio

from app.api.v1.endpoints.health import migration_summary
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def run(setup_sql):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                for stmt in setup_sql:
                    await db.execute(text(stmt))
                return await migration_summary(db)
        finally:
            await engine.dispose()

    return asyncio.run(main())


TABLE = "CREATE TABLE aisoc_schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT)"


def test_the_count_and_the_newest_migration_by_name():
    got = run(
        [
            TABLE,
            "INSERT INTO aisoc_schema_migrations VALUES ('099_a.sql','2026-01-01'), ('148_z.sql','2026-11-04'), ('100_b.sql','2026-02-01')",
        ]
    )
    assert got == {"applied": 3, "newest": "148_z.sql", "applied_at": "2026-11-04"}


def test_an_empty_table_is_zero_applied_with_no_newest():
    assert run([TABLE]) == {"applied": 0, "newest": None, "applied_at": None}


def test_a_database_that_cannot_be_read_gives_none_not_a_made_up_count():
    assert run([]) is None  # there is no migrations table at all
