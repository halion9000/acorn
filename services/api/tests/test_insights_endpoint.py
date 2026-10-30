"""Tests for the SOC Insights aggregator endpoint (T3.1).

The endpoint at ``/api/v1/insights/soc`` shapes a one-shot payload for the
SOC Insights dashboard: 7 tiles, each with a current value, a previous-
window comparison, an optional ``delta_pct``, and a 24-point sparkline.

The aggregation logic is a pure mix of SQLAlchemy aggregates plus the
named ``MANUAL_INVESTIGATION_MINUTES`` heuristic. We test it the same
way the rest of the API service tests its endpoint helpers — using a
``MagicMock`` ``AsyncSession`` whose ``scalar`` / ``execute`` return
canned values per call — so the suite stays fast and deterministic.

Coverage targets:

* ``_delta_pct`` — math + the "previous window had no data" branch
  (``None`` rather than ``inf``).
* ``_window_to_timedelta`` — clamping to the {24h, 7d, 30d} allowlist.
* End-to-end shape of ``get_soc_insights`` against seeded numbers, so a
  schema regression (renamed tile key, missing field, off-by-one in the
  ordering) is caught here and not at runtime in the browser.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import insights as ins
from app.api.v1.endpoints.insights import (
    MANUAL_INVESTIGATION_MINUTES,
    SOCInsightsResponse,
    _delta_pct,
    _merge_parts,
    _window_to_timedelta,
    get_soc_insights,
)
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_delta_pct_basic() -> None:
    # 5 → 10 is +100%
    assert _delta_pct(10.0, 5.0) == 100.0


def test_delta_pct_negative_change() -> None:
    # 10 → 5 is -50%
    assert _delta_pct(5.0, 10.0) == -50.0


def test_delta_pct_no_previous_data_returns_none() -> None:
    """Previous-window zero must be ``None`` (undefined), not infinity.

    The UI renders ``None`` as an em-dash; an infinity here would
    serialize as ``"Infinity"`` and corrupt JSON parsing on the client.
    """
    assert _delta_pct(7.0, 0.0) is None


def test_delta_pct_no_change_is_zero() -> None:
    assert _delta_pct(4.5, 4.5) == 0.0


def test_window_to_timedelta_accepts_24h() -> None:
    assert _window_to_timedelta("24h").days == 1


def test_window_to_timedelta_accepts_7d() -> None:
    assert _window_to_timedelta("7d").days == 7


def test_window_to_timedelta_accepts_30d() -> None:
    assert _window_to_timedelta("30d").days == 30


def test_window_to_timedelta_rejects_unknown() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _window_to_timedelta("1y")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# End-to-end endpoint shape
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    """The endpoint keeps an answer for a few seconds; each test here must compute its own. The second row of tiles reads the database in grouped statements a mock cannot answer: it has its
    own tests on a real Postgres (test_insight_tiles_postgres.py), so here it is switched off and these tests are about the first seven tiles."""

    async def no_extras(*_a, **_k):
        return []

    monkeypatch.setattr(ins, "_gather_extras", no_extras)
    # The mocked database here answers the per-tenant statements; the grouped ones are checked against these on a real Postgres (test_insight_tiles_postgres.py).
    monkeypatch.setattr(ins, "_scope_totals", ins._scope_totals_per_tenant)
    ins._cache.clear()
    ins._locks.clear()
    yield
    ins._cache.clear()
    ins._locks.clear()


def _stub_user() -> SimpleNamespace:
    """Minimal ``CurrentUser`` stand-in (only ``tenant_id`` is read)."""
    return SimpleNamespace(tenant_id=uuid.uuid4())


class _FakeMappings:
    """Cursor-shaped object that satisfies ``.first()`` and iteration."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []

    def first(self):  # noqa: D401 - mirror SQLAlchemy
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _FakeResult:
    """Stand-in for ``Result`` that exposes both ``.all()`` and ``.mappings()``."""

    def __init__(self, rows: list | None = None, mappings: list[dict] | None = None) -> None:
        self._rows = rows or []
        self._mappings = mappings or []

    def all(self) -> list:
        return self._rows

    def mappings(self) -> _FakeMappings:
        return _FakeMappings(self._mappings)


def _seeded_db(scalar_value: int = 5) -> MagicMock:
    """Build an AsyncSession-shaped mock that returns deterministic numbers.

    The endpoint calls ``db.scalar`` and ``db.execute`` many times. We
    return a *fresh* value each call so we can verify the response
    builds without exception and that every tile is populated.

    Numeric values are deliberately picked so the deltas are easy to
    eyeball when the test fails — e.g. current = 10, previous = 5 →
    +100%.
    """
    db = MagicMock()

    # Scalars (current values, then previous-window comparisons + counts).
    # We return the same value for every call — the goal is to assert
    # the tile shape, not the exact arithmetic. The hours-saved test
    # uses a dedicated seed to exercise the heuristic specifically.
    db.scalar = AsyncMock(return_value=scalar_value)

    # ``execute`` is used three places:
    #   * sparkline alerts query → ``.all()`` of (timestamp,) tuples
    #   * sparkline cases  query → ``.all()`` of (timestamp,) tuples
    #   * cost queries (text SQL) → ``.mappings().first()`` / iteration.
    # Empty rows + empty mappings is the "nothing seeded" baseline.
    async def _execute(*_args, **_kwargs):
        return _FakeResult()

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_get_soc_insights_returns_seven_tiles_with_expected_keys() -> None:
    """The dashboard depends on a stable seven-tile shape — lock it in."""
    db = _seeded_db()
    user = _stub_user()

    response = await get_soc_insights(user=user, db=db, window="24h")

    assert isinstance(response, SOCInsightsResponse)
    assert response.window == "24h"
    assert response.manual_investigation_minutes == MANUAL_INVESTIGATION_MINUTES
    assert response.tenant_id == user.tenant_id
    assert isinstance(response.generated_at, datetime)
    assert response.generated_at.tzinfo == UTC

    keys = [tile.key for tile in response.tiles]
    assert keys == [
        "mtta",
        "mttr",
        "fp_rate",
        "alerts_per_day",
        "cases_per_day",
        "agent_cost_per_investigation",
        "analyst_hours_saved",
    ]

    # Every tile must have a sparkline of exactly 24 points so the SVG
    # renderer can rely on the bucket count without a runtime check.
    for tile in response.tiles:
        assert len(tile.sparkline.points) == 24
        # Sparkline points are floats — the frontend formats them with
        # ``Number(...)`` so an int would also pass, but locking the
        # type prevents accidental Decimal leakage.
        for point in tile.sparkline.points:
            assert isinstance(point, int | float)


@pytest.mark.asyncio
async def test_get_soc_insights_hours_saved_uses_named_constant() -> None:
    """The hours-saved tile must derive its value from the named heuristic.

    Operators expect to be able to tune ``MANUAL_INVESTIGATION_MINUTES``
    in one place and have the number ripple through both the JSON
    payload (so the docs/tooltip stay accurate) and the tile value.
    """
    # Every scalar — including ``_count(... Case.status == 'resolved')``
    # — returns 4. 4 auto-closed cases × 45 min = 180 min = 3.0 h saved.
    db = _seeded_db(scalar_value=4)
    user = _stub_user()

    response = await get_soc_insights(user=user, db=db, window="24h")

    hours_saved_tile = next(t for t in response.tiles if t.key == "analyst_hours_saved")
    expected_hours = round((4 * MANUAL_INVESTIGATION_MINUTES) / 60.0, 2)
    assert hours_saved_tile.value == expected_hours
    assert hours_saved_tile.unit == "hours_saved"


@pytest.mark.asyncio
async def test_get_soc_insights_rejects_unknown_window() -> None:
    """Tenants can't sneak a 365-day scan past us via the query string."""
    db = _seeded_db()
    user = _stub_user()

    with pytest.raises(HTTPException) as exc_info:
        await get_soc_insights(user=user, db=db, window="1y")  # type: ignore[arg-type]
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_soc_insights_zero_state_renders_without_500() -> None:
    """Fresh tenant: no alerts, no cases — payload should still render.

    The dashboard needs to render the day a tenant onboards. Returning
    7 tiles of zero with ``delta_pct == None`` is preferable to a 500
    or a blank page.
    """
    db = _seeded_db(scalar_value=0)
    user = _stub_user()

    response = await get_soc_insights(user=user, db=db, window="7d")

    assert response.window == "7d"
    assert len(response.tiles) == 7
    for tile in response.tiles:
        # Both current and previous are zero, so delta is undefined.
        assert tile.value == 0 or tile.value == 0.0
        assert tile.delta_pct is None


def _part(alerts: int, mtta: tuple[float, int], fp: tuple[int, int], spark: float) -> dict:
    out: dict = {}
    for tag in ("", "prev_"):
        out[tag + "mtta"] = mtta
        out[tag + "mttr"] = (0.0, 0)
        out[tag + "fp"] = fp
        out[tag + "alerts"] = alerts
        out[tag + "cases"] = 0
        out[tag + "runs"] = 0
        out[tag + "cost"] = 0.0
        out[tag + "auto_closed"] = 0
    out["alert_spark"] = [spark] * 24
    out["case_spark"] = [0.0] * 24
    out["cost_spark"] = [0.0] * 24
    return out


def test_merge_parts_rolls_clients_into_parent() -> None:
    """Parent has nothing; clients hold the alerts — totals must include them."""
    parent = _part(0, (0.0, 0), (0, 0), 0.0)
    a = _part(20, (1.0, 10), (1, 4), 1.0)
    b = _part(8, (4.0, 30), (3, 4), 2.0)

    total = _merge_parts([parent, a, b])

    assert total["alerts"] == 28
    # weighted by sample size: (1*10 + 4*30) / 40 = 3.25, not the plain 2.5
    assert total["mtta"] == 3.25
    assert total["fp"] == 0.5  # 4 false positives of 8 dispositioned
    assert total["alert_spark"] == [3.0] * 24
    assert total["mttr"] == 0.0  # no samples anywhere: zero, not a divide error


@pytest.mark.asyncio
async def test_get_soc_insights_includes_child_tenants() -> None:
    """Every client tenant under the caller is queried, not just the caller."""
    child_ids = [uuid.uuid4(), uuid.uuid4()]
    db = _seeded_db(scalar_value=2)

    async def _execute(stmt, *_a, **_k):
        if "parent_tenant_id" in str(stmt):
            return _FakeResult(rows=[(c,) for c in child_ids])
        return _FakeResult()

    db.execute = AsyncMock(side_effect=_execute)
    response = await get_soc_insights(user=_stub_user(), db=db, window="7d")

    alerts_tile = next(t for t in response.tiles if t.key == "alerts_per_day")
    # 3 tenants x 2 alerts each / 7 days
    assert alerts_tile.value == round(6 / 7, 2)


def _db_with_history(first_alert: datetime | None, current: int = 10) -> MagicMock:
    """A mocked session whose tenant's first alert was recorded at ``first_alert``; every other count is ``current``."""
    db = _seeded_db(scalar_value=current)

    async def _scalar(stmt, *_a, **_k):
        return first_alert if "min(" in str(stmt).lower() else current

    db.scalar = AsyncMock(side_effect=_scalar)
    return db


@pytest.mark.asyncio
async def test_no_change_figure_until_the_data_covers_the_whole_earlier_window() -> None:
    """Three days of history cannot be compared with the 7 days before them: +1500% would only mean the platform is new."""
    now = datetime.now(UTC)
    response = await get_soc_insights(user=_stub_user(), db=_db_with_history(now - timedelta(days=3)), window="7d")
    assert response.comparison_ready is False
    assert response.history_since is not None
    assert all(t.delta_pct is None for t in response.tiles)


@pytest.mark.asyncio
async def test_change_figures_appear_once_the_earlier_window_is_covered() -> None:
    now = datetime.now(UTC)
    response = await get_soc_insights(user=_stub_user(), db=_db_with_history(now - timedelta(days=20)), window="7d")
    assert response.comparison_ready is True
    assert any(t.delta_pct is not None for t in response.tiles)


@pytest.mark.asyncio
async def test_a_tenant_with_no_alerts_has_no_comparison() -> None:
    response = await get_soc_insights(user=_stub_user(), db=_db_with_history(None, current=0), window="24h")
    assert response.comparison_ready is False and response.history_since is None


def _db_with_clients(client_ids: list, scalar_value: int = 2) -> MagicMock:
    db = _seeded_db(scalar_value=scalar_value)

    async def _execute(stmt, *_a, **_k):
        if "parent_tenant_id" in str(stmt):
            return _FakeResult(rows=[(c,) for c in client_ids])
        return _FakeResult()

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_one_client_shows_only_that_clients_numbers() -> None:
    """With a client picked, the organization and its other clients are left out (3 tenants x 2 alerts would be 6; one client is 2)."""
    clients = [uuid.uuid4(), uuid.uuid4()]
    response = await get_soc_insights(user=_stub_user(), db=_db_with_clients(clients), window="7d", client_id=clients[0])
    alerts = next(t for t in response.tiles if t.key == "alerts_per_day")
    assert alerts.value == round(2 / 7, 2)


@pytest.mark.asyncio
async def test_a_client_that_is_not_this_organizations_is_a_404() -> None:
    clients = [uuid.uuid4()]
    with pytest.raises(HTTPException) as e:
        await get_soc_insights(user=_stub_user(), db=_db_with_clients(clients), window="7d", client_id=uuid.uuid4())
    assert e.value.status_code == 404
    with pytest.raises(HTTPException):
        # the organization's own id is not a client either
        user = _stub_user()
        await get_soc_insights(user=user, db=_db_with_clients(clients), window="7d", client_id=user.tenant_id)


@pytest.mark.asyncio
async def test_a_second_request_for_the_same_view_within_seconds_is_the_kept_answer_and_a_burst_shares_one_computation(monkeypatch):
    calls = []

    async def fake_build(user, db, window, client_id):
        calls.append((window, client_id))
        await asyncio.sleep(0.05)
        return SimpleNamespace(window=window, n=len(calls))

    monkeypatch.setattr(ins, "_build_soc_insights", fake_build)
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    burst = await asyncio.gather(*[ins.get_soc_insights(user, None, "24h", None) for _ in range(5)])
    assert len(calls) == 1 and {b.n for b in burst} == {1}, "five identical requests at once are one computation"
    assert (await ins.get_soc_insights(user, None, "24h", None)).n == 1, "and the next one is the kept answer"
    assert (await ins.get_soc_insights(user, None, "7d", None)).n == 2, "another window is its own answer"
    assert (
        await ins.get_soc_insights(SimpleNamespace(tenant_id=uuid.uuid4()), None, "24h", None)
    ).n == 3, "another organization never sees this one's"
    monkeypatch.setattr(ins, "CACHE_SECONDS", 0.0)
    assert (await ins.get_soc_insights(user, None, "24h", None)).n == 4, "after the time is up it is computed again"
