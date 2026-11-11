"""The biggest tables on the health page: sizes in megabytes, an unknown row estimate shown as unknown, and a page that never breaks when the sizes cannot be read."""

import asyncio
import contextlib

from app.api.v1.endpoints import health as ep

MB = 1024 * 1024


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class Db:
    def __init__(self, rows=(), boom=False):
        self.rows, self.boom, self.statements = list(rows), boom, []

    def begin_nested(self):
        return contextlib.nullcontext()

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if self.boom:
            raise RuntimeError("permission denied")
        return Result(self.rows)


def test_tables_are_listed_in_megabytes_with_an_unknown_estimate_shown_as_none():
    db = Db(rows=[("alerts", 1536 * MB, 1_200_000), ("brand_new", 8192, -1)])
    out = asyncio.run(ep.table_sizes(db))
    assert out["available"] is True and out["note"] is None
    assert out["tables"] == [
        {"table": "alerts", "megabytes": 1536.0, "rows_estimate": 1_200_000},
        {"table": "brand_new", "megabytes": 0.0, "rows_estimate": None},
    ]
    text, params = db.statements[0]
    assert "pg_total_relation_size" in text and "ORDER BY" in text and params == {"n": ep.TABLE_SIZES_SHOWN}


def test_an_account_that_cannot_read_them_says_so_and_never_breaks_the_page():
    out = asyncio.run(ep.table_sizes(Db(boom=True)))
    assert out["available"] is False and "could not be read" in out["note"] and out["tables"] == []


import os  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")


@pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")
def test_the_real_query_lists_the_largest_tables_biggest_first():
    async def go():
        engine = create_async_engine(PG_URL, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                return await ep.table_sizes(db)
        finally:
            await engine.dispose()

    out = asyncio.run(go())
    assert out["available"] is True and 0 < len(out["tables"]) <= ep.TABLE_SIZES_SHOWN
    sizes = [t["megabytes"] for t in out["tables"]]
    assert sizes == sorted(sizes, reverse=True)
