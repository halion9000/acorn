"""Slow database queries on the health page: listed only where the database keeps statistics, and saying so where it does not or cannot be read."""

import asyncio
import contextlib

from app.api.v1.endpoints import health as ep


class Result:
    def __init__(self, rows):
        self.rows = rows

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class Db:
    def __init__(self, installed=True, rows=(), boom=False):
        self.installed, self.rows, self.boom = installed, list(rows), boom
        self.statements = []

    def begin_nested(self):
        return contextlib.nullcontext()

    async def execute(self, statement, params=None):
        text = str(statement)
        self.statements.append((text, params))
        if self.boom:
            raise RuntimeError("permission denied for pg_stat_statements")
        if "pg_extension" in text:
            return Result([(1,)] if self.installed else [])
        return Result(self.rows)


def test_the_slowest_statements_are_listed_cut_short_with_times_in_seconds():
    long = "SELECT   *\n FROM alerts WHERE id = $1 " + "x" * 400
    db = Db(rows=[(long, 12, 2500.0, 30000.0), ("UPDATE t SET a = $1", 7, 40.0, 280.0)])
    out = asyncio.run(ep.slow_queries(db))
    assert out["available"] is True and out["note"] is None
    first, second = out["queries"]
    assert (
        first["query"].startswith("SELECT * FROM alerts WHERE id = $1 x") and len(first["query"]) == ep.SLOW_QUERY_TEXT
    ), "whitespace folded, cut short"
    assert (first["calls"], first["typical_seconds"], first["total_seconds"]) == (12, 2.5, 30.0)
    assert (second["typical_seconds"], second["total_seconds"]) == (0.04, 0.3)
    text, params = db.statements[1]
    assert "ORDER BY mean_exec_time DESC" in text and params == {"calls": ep.SLOW_QUERY_MIN_CALLS, "n": ep.SLOW_QUERIES_SHOWN}
    assert "pg_stat_statements" in text and "NOT ILIKE" in text, "its own query is not listed"


def test_a_database_without_the_extension_says_so_and_does_not_look_for_rows():
    db = Db(installed=False)
    out = asyncio.run(ep.slow_queries(db))
    assert out["available"] is False and "not installed" in out["note"] and out["queries"] == []
    assert len(db.statements) == 1


def test_an_account_that_cannot_read_the_statistics_says_so_and_never_breaks_the_page():
    out = asyncio.run(ep.slow_queries(Db(boom=True)))
    assert out["available"] is False and "could not be read" in out["note"] and out["queries"] == []


def test_no_rows_yet_is_available_with_an_empty_list_not_unavailable():
    out = asyncio.run(ep.slow_queries(Db(rows=[])))
    assert out == {"available": True, "note": None, "queries": []}
