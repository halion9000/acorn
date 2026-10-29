"""The list of hide-this-alert-type rules says when it is incomplete.

Before: a count that could not be read showed as "hides 0 alerts", and the list stopped at 500 rules without saying so.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.api.v1.endpoints import alert_suppressions as ep
from fastapi import Response

NOW = datetime.now(UTC)
OWNER = uuid.uuid4()
GOOD_CLIENT, BAD_CLIENT = uuid.uuid4(), uuid.uuid4()


def rule(scope="client", client=None, title="Printer offline"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        scope=scope,
        client_tenant_id=client,
        device_key=None,
        source=None,
        title=title,
        expires_at=None,
        created_at=NOW - timedelta(days=1),
        revoked_at=None,
        signature="title:" + title,
    )


def fake_db(rules, total, counts_by_tenant, failing=()):
    """Answers each statement by what it reads: the number of rules, the rules, the client names, or one client's counts of hidden alerts (which can fail)."""
    db = MagicMock()
    seen = {"tenants": [], "total": None, "limit": None}

    async def execute(stmt):
        sql = str(stmt.compile())
        params = stmt.compile().params
        result = MagicMock()
        if "count(*)" in sql and "alert_suppressions" in sql and "alerts" not in sql.split("FROM")[-1]:
            seen["total"] = total
            result.scalar_one = MagicMock(return_value=total)
        elif "FROM alert_suppressions" in sql:
            seen["limit"] = [v for k, v in params.items() if k.startswith("param_")]
            result.scalars = MagicMock(return_value=SimpleNamespace(all=lambda: rules))
        elif "FROM tenants" in sql:
            result.all = MagicMock(
                return_value=[SimpleNamespace(id=GOOD_CLIENT, name="Good Co"), SimpleNamespace(id=BAD_CLIENT, name="Bad Co")]
            )
        else:
            tenant = next(v for v in params.values() if isinstance(v, uuid.UUID))
            seen["tenants"].append(tenant)
            if tenant in failing:
                raise RuntimeError("the database could not count")
            result.all = MagicMock(return_value=counts_by_tenant.get(tenant, []))
        return result

    db.execute = AsyncMock(side_effect=execute)
    db.seen = seen
    return db


def run(rules, total, counts, failing=(), **kw):
    db = fake_db(rules, total, counts, failing)
    response = Response()
    out = asyncio.run(
        ep.list_suppressions(SimpleNamespace(tenant_id=OWNER), db, response, **{"include_ended": False, "limit": 500, "offset": 0, **kw})
    )
    return out, response, db


def test_a_count_that_cannot_be_read_is_unknown_not_zero():
    good, bad = rule(client=GOOD_CLIENT, title="Good rule"), rule(client=BAD_CLIENT, title="Bad rule")
    out, _resp, _db = run([good, bad], 2, {GOOD_CLIENT: [(good.id, 4)]}, failing=(BAD_CLIENT,))
    by_title = {o.title: o for o in out}
    assert by_title["Good rule"].hidden_alerts == 4
    assert by_title["Bad rule"].hidden_alerts is None, "unknown, not 'hides 0 alerts'"


def test_a_rule_for_all_clients_is_unknown_if_any_client_could_not_be_counted_and_a_sum_otherwise():
    everywhere = rule(scope="all", title="Everywhere")
    out, _r, _d = run([everywhere], 1, {GOOD_CLIENT: [(everywhere.id, 3)], OWNER: [(everywhere.id, 2)]}, failing=(BAD_CLIENT,))
    assert out[0].hidden_alerts is None
    out, _r, _d = run([everywhere], 1, {GOOD_CLIENT: [(everywhere.id, 3)], OWNER: [(everywhere.id, 2)], BAD_CLIENT: [(everywhere.id, 1)]})
    assert out[0].hidden_alerts == 6


def test_a_count_that_fails_does_not_fail_the_list_and_no_failure_means_numbers_everywhere():
    quiet = rule(client=GOOD_CLIENT)
    out, _r, _d = run([quiet], 1, {})
    assert out[0].hidden_alerts == 0, "counted and none hidden is a real zero"
    out, _r, _d = run([quiet], 1, {}, failing=(OWNER, GOOD_CLIENT, BAD_CLIENT))
    assert [o.hidden_alerts for o in out] == [None]


def test_the_total_is_in_a_header_so_a_cut_list_is_known_to_be_cut():
    rules = [rule(title=f"r{i}") for i in range(3)]
    _out, response, _db = run(rules, 1234, {}, limit=3)
    assert response.headers["X-Total-Count"] == "1234"
    _out, response, _db = run([], 0, {})
    assert response.headers["X-Total-Count"] == "0"
