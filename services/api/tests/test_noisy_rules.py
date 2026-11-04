"""The noisy-rule report: how a rule's line is worked out, what the query counts, and that the route only reads."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import alert_suppressions as ep
from sqlalchemy.dialects import postgresql


def test_a_rule_with_many_alerts_mostly_false_positives_is_worth_suggesting_to_hide():
    r = ep.noisy_row("Disk space low", "ninjaone", 40, 5, 30)
    assert (r.total, r.open, r.false_positives, r.false_positive_rate, r.suggest_hide) == (40, 5, 30, 0.75, True)


def test_a_few_alerts_or_few_false_positives_or_a_low_share_is_not_noise():
    assert ep.noisy_row("x", None, 9, 0, 9).suggest_hide is False  # too few to call a pattern
    assert ep.noisy_row("x", None, 40, 0, 2).suggest_hide is False  # under three false positives
    assert ep.noisy_row("x", None, 100, 0, 30).suggest_hide is False  # under half
    assert ep.noisy_row("x", None, 0, 0, 0).false_positive_rate == 0.0


class Db:
    def __init__(self, rows):
        self.statements = []

        async def execute(statement):
            self.statements.append(statement)
            out = MagicMock()
            out.all.return_value = rows
            return out

        self.execute = AsyncMock(side_effect=execute)


@pytest.fixture
def wired(monkeypatch):
    import app.api.v1.endpoints.devices as devices
    import app.db.rls_scope as rls

    monkeypatch.setattr(devices, "_scope", AsyncMock(return_value=([uuid.uuid4()], {})))
    monkeypatch.setattr(rls, "cross_tenant_reads", lambda db: contextlib.nullcontext())


def test_the_report_lists_the_rules_in_the_order_the_query_gives_with_each_line_worked_out(wired):
    db = Db([("Disk space low", "ninjaone", 40, 5, 30), ("Impossible travel", "aisoc-checks", 12, 12, 0)])
    out = asyncio.run(ep.noisy_rules(NS(tenant_id=uuid.uuid4()), db, None, 30, 10))
    assert [r.name for r in out] == ["Disk space low", "Impossible travel"]
    assert out[0].suggest_hide is True and out[1].suggest_hide is False


def test_the_query_counts_only_alerts_still_in_play_names_a_rule_by_its_rule_or_title_and_only_reads(wired):
    db = Db([])
    asyncio.run(ep.noisy_rules(NS(tenant_id=uuid.uuid4()), db, None, 7, 5))
    text = str(db.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "coalesce(alerts.rule_name, alerts.title)" in text
    assert "alerts.status NOT IN ('suppressed', 'stale')" in text
    assert "LIMIT 5" in text and text.lstrip().upper().startswith("SELECT")


def test_the_route_needs_alerts_read_only():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    assert set(required_permissions(found[("GET", "/alert-suppressions/noisy")])) == {"alerts:read"}
