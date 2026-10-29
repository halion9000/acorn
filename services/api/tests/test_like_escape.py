"""What a person types into a search box is text, not a pattern: ``%`` and ``_`` match themselves.

The audit log's ``action`` and ``search`` filters put the text straight into a LIKE, so ``search=%`` matched every row and ``action=cases_`` matched ``casesXupdate``.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from app.api.v1.endpoints.audit import _filtered_audit_query
from app.services.like import ESCAPE, escape_like
from sqlalchemy.dialects import postgresql

ROWS = ["cases:update", "casesXupdate", "50% off", "50 percent", "a_b", "axb", "back\\slash", "backXslash", "100%"]


def matching(pattern: str) -> list[str]:
    """Run the pattern through a real SQL LIKE (SQLite's, which has the same wildcard rules), with the escape character the filters use."""
    db = sqlite3.connect(":memory:")
    db.execute("create table t (a text)")
    db.executemany("insert into t values (?)", [(r,) for r in ROWS])
    return [r[0] for r in db.execute(f"select a from t where a like ? escape '{ESCAPE}' order by rowid", (pattern,))]


def test_the_escape_character_percent_and_underscore_are_escaped():
    assert escape_like("50%") == "50\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("back\\slash") == "back\\\\slash"
    assert escape_like("plain text") == "plain text"
    assert escape_like("") == ""


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("%", ["50% off", "100%"]),
        ("_", ["a_b"]),
        ("a_b", ["a_b"]),
        ("50%", ["50% off"]),
        ("back\\slash", ["back\\slash"]),
        ("cases:", ["cases:update"]),
    ],
)
def test_a_substring_search_matches_the_text_literally(typed, expected):
    assert matching(f"%{escape_like(typed)}%") == expected


def test_a_prefix_filter_matches_the_prefix_literally():
    assert matching(f"{escape_like('cases:')}%") == ["cases:update"]
    assert matching(f"{escape_like('a_')}%") == ["a_b"], "an underscore is not 'any one character'"
    assert matching(f"{escape_like('%')}%") == [], "a percent sign is not 'everything'"


def _sql(**kw) -> str:
    args = {"tenant_id": uuid.uuid4(), "action": None, "resource": None, "actor_id": None, "search": None} | kw
    sql = str(_filtered_audit_query(**args).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    return sql.replace("%%", "%")  # the driver's own doubling of a percent sign in rendered SQL


def test_the_audit_filters_escape_what_was_typed_and_say_which_escape_character():
    sql = _sql(action="cases_", search="50%")
    assert "LIKE 'cases\\_%' ESCAPE '\\'" in sql, sql
    assert "ILIKE '%50\\%%' ESCAPE '\\'" in sql, sql
    assert sql.count("ESCAPE") == 3, "the prefix, and the search on the action and on the e-mail address"


def test_no_filter_means_no_like_at_all():
    assert "LIKE" not in _sql()
