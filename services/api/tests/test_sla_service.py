"""The SLA maths and the event endpoint, tested directly.

The duration, merge and report functions had no test of their own. These also pin the defaults ("info" was defined twice, with different values, neither equal to the migration's seed), the timestamps (naive times made a comparison raise, and the report's
``computed_at`` had no offset) and the event endpoint (any alert id, a naive or future time and unbounded metadata were accepted).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import sla as ep
from app.db.database import Base
from app.models.sla import AlertSLAEvent, TenantSLAConfig
from app.models.tenant import Tenant
from app.services import sla
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

T0 = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)


def event(kind, minutes, severity="high", alert=None, naive=False):
    at = T0 + timedelta(minutes=minutes)
    return SimpleNamespace(
        event_type=kind, occurred_at=at.replace(tzinfo=None) if naive else at, severity=severity, alert_id=alert or uuid.uuid4()
    )


class TestDurations:
    def test_minutes_from_detected_to_each_later_step(self):
        d = sla._compute_durations([event("detected", 0), event("acknowledged", 12), event("resolved", 90), event("closed", 150)])
        assert (d["mttd"], d["mttr"], d["mttc"], d["severity"]) == (12, 90, 150, "high")

    def test_a_step_that_has_not_happened_is_none(self):
        d = sla._compute_durations([event("detected", 0), event("acknowledged", 5)])
        assert (d["mttd"], d["mttr"], d["mttc"]) == (5, None, None)
        assert sla._compute_durations([event("acknowledged", 5)])["mttd"] is None, "no detection, no duration"

    def test_a_step_recorded_before_detection_is_none_not_negative(self):
        d = sla._compute_durations([event("detected", 30), event("acknowledged", 10)])
        assert d["mttd"] is None

    def test_whole_minutes_are_cut_down_and_the_same_instant_is_zero(self):
        at = T0
        events = [
            SimpleNamespace(event_type="detected", occurred_at=at, severity="low", alert_id=uuid.uuid4()),
            SimpleNamespace(event_type="acknowledged", occurred_at=at + timedelta(seconds=119), severity="low", alert_id=uuid.uuid4()),
            SimpleNamespace(event_type="resolved", occurred_at=at, severity="low", alert_id=uuid.uuid4()),
        ]
        d = sla._compute_durations(events)
        assert (d["mttd"], d["mttr"]) == (1, 0)

    def test_naive_and_aware_times_can_be_mixed_without_an_error(self):
        d = sla._compute_durations([event("detected", 0, naive=True), event("acknowledged", 7), event("resolved", 20, naive=True)])
        assert (d["mttd"], d["mttr"]) == (7, 20)

    def test_no_events_has_an_unknown_severity(self):
        d = sla._compute_durations([])
        assert (d["mttd"], d["mttr"], d["mttc"], d["severity"]) == (None, None, None, "unknown")

    def test_the_last_event_of_a_kind_wins(self):
        d = sla._compute_durations([event("detected", 0), event("acknowledged", 5), event("acknowledged", 25)])
        assert d["mttd"] == 25


class TestMerges:
    def test_the_four_known_keys_come_back_with_defaults_and_numbers(self):
        out = sla.merge_kpi_bar_dict(None, {})
        assert out == sla.DEFAULT_KPI_BAR_TARGETS
        merged = sla.merge_kpi_bar_dict({"false_positive_rate_max_pct": "7.5"}, {"alert_to_incident_ratio_min": 40})
        assert merged["false_positive_rate_max_pct"] == 7.5 and merged["alert_to_incident_ratio_min"] == 40.0
        assert merged["mitre_technique_tagging_min_pct"] == sla.DEFAULT_KPI_BAR_TARGETS["mitre_technique_tagging_min_pct"]

    def test_unknown_keys_and_non_numbers_are_dropped_not_stored(self):
        out = sla.merge_kpi_bar_dict({"banana": 1, "false_positive_rate_max_pct": "lots"}, {"mitre_technique_tagging_min_pct": None})
        assert set(out) == set(sla.DEFAULT_KPI_BAR_TARGETS)
        assert out["false_positive_rate_max_pct"] == sla.DEFAULT_KPI_BAR_TARGETS["false_positive_rate_max_pct"]
        assert out["mitre_technique_tagging_min_pct"] == sla.DEFAULT_KPI_BAR_TARGETS["mitre_technique_tagging_min_pct"]

    def test_a_settings_patch_replaces_keys_but_merges_the_kpi_bar_only(self):
        existing = {"theme": "dark", "kpi_bar": {"false_positive_rate_max_pct": 9.0}, "keep": 1}
        out = sla.merge_tenant_settings_patch(existing, {"theme": "light", "kpi_bar": {"alert_to_incident_ratio_min": 30}, "new": True})
        assert out["theme"] == "light" and out["keep"] == 1 and out["new"] is True
        assert out["kpi_bar"]["false_positive_rate_max_pct"] == 9.0 and out["kpi_bar"]["alert_to_incident_ratio_min"] == 30.0
        assert existing["kpi_bar"] == {"false_positive_rate_max_pct": 9.0}, "the stored settings are not changed in place"

    def test_a_kpi_bar_that_is_not_a_dict_is_replaced_by_the_patch(self):
        assert (
            sla.merge_tenant_settings_patch({"kpi_bar": "junk"}, {"kpi_bar": {"false_positive_rate_max_pct": 3}})["kpi_bar"][
                "false_positive_rate_max_pct"
            ]
            == 3.0
        )
        assert sla.merge_tenant_settings_patch(None, {"a": 1}) == {"a": 1}


def test_there_is_one_set_of_default_targets_and_info_matches_the_migrations_seed():
    assert set(sla.DEFAULT_SLA_TARGETS) == {"critical", "high", "medium", "low", "info"}
    # Migration 040 seeds "info" as 240 / 1440 / 4320; the code used to say 240 / 960 / 2880 in one place and 480 / 1440 / 2880 in another.
    assert sla.DEFAULT_SLA_TARGETS["info"] == {"mttd_target": 240, "mttr_target": 1440, "mttc_target": 4320}
    for tiers in zip(*[list(sla.DEFAULT_SLA_TARGETS[s].values()) for s in ("critical", "high", "medium", "low", "info")], strict=True):
        assert list(tiers) == sorted(tiers), "a lower severity never has a tighter target"


def run(fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(
                lambda conn: Base.metadata.create_all(conn, tables=[Tenant.__table__, TenantSLAConfig.__table__, AlertSLAEvent.__table__])
            )
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


def lifecycle(db, tenant, severity, steps, age_days=1):
    """Add one alert's events: steps is [(kind, minutes after detection)]."""
    alert = uuid.uuid4()
    start = datetime.now(UTC) - timedelta(days=age_days)
    for kind, minutes in steps:
        db.add(
            AlertSLAEvent(
                tenant_id=tenant,
                alert_id=alert,
                severity=severity,
                event_type=kind,
                occurred_at=start + timedelta(minutes=minutes),
                metadata_={},
            )
        )


def test_the_report_counts_breaches_per_severity_and_overall(monkeypatch):
    monkeypatch.setattr(sla, "get_settings", lambda: SimpleNamespace(AISOC_FEATURE_KPI_BAR=False))

    async def body(s):
        t = Tenant(id=uuid.uuid4(), name="Acme", slug="acme")
        s.add(t)
        await s.flush()
        lifecycle(s, t.id, "critical", [("detected", 0), ("acknowledged", 10), ("resolved", 50)])  # inside 15 / 60
        lifecycle(s, t.id, "critical", [("detected", 0), ("acknowledged", 40), ("resolved", 100)])  # over 15 and 60
        lifecycle(s, t.id, "info", [("detected", 0), ("acknowledged", 200)])  # inside the default 240
        lifecycle(s, t.id, "info", [("detected", 0), ("acknowledged", 300)])  # over the default 240
        lifecycle(s, t.id, "low", [("detected", 0), ("acknowledged", 10)], age_days=45)  # outside a 30-day window
        await s.commit()
        return await sla.compute_sla_metrics(s, t.id, days=30)

    out = run(body)
    crit, info = out["per_severity"]["critical"], out["per_severity"]["info"]
    assert (crit["total"], crit["breaches"], crit["breach_rate"]) == (2, 1, 50.0)
    assert crit["mttd_avg"] == 25.0 and crit["mttr_avg"] == 75.0 and crit["mttc_avg"] is None
    assert (crit["mttd_target"], crit["mttr_target"]) == (15, 60)
    assert (info["total"], info["breaches"]) == (2, 1)
    assert info["mttd_target"] == 240, "no row for the tenant: the one default is used"
    assert out["per_severity"]["low"]["total"] == 0, "an event older than the window is not counted"
    assert out["overall"]["total_alerts"] == 4 and out["overall"]["total_breaches"] == 2 and out["overall"]["breach_rate"] == 50.0
    assert out["kpi_bar"] is None and out["period_days"] == 30


def test_a_tenants_own_targets_beat_the_defaults_and_the_time_has_an_offset(monkeypatch):
    monkeypatch.setattr(sla, "get_settings", lambda: SimpleNamespace(AISOC_FEATURE_KPI_BAR=False))

    async def body(s):
        t = Tenant(id=uuid.uuid4(), name="Acme", slug="acme")
        s.add(t)
        await s.flush()
        s.add(TenantSLAConfig(tenant_id=t.id, severity="high", mttd_target=5, mttr_target=10, mttc_target=20))
        lifecycle(s, t.id, "high", [("detected", 0), ("acknowledged", 8)])  # over the tenant's 5, inside the default 30
        await s.commit()
        return await sla.compute_sla_metrics(s, t.id, days=7)

    out = run(body)
    assert out["per_severity"]["high"]["breaches"] == 1 and out["per_severity"]["high"]["mttd_target"] == 5
    assert out["computed_at"].endswith("+00:00"), out["computed_at"]
    assert datetime.fromisoformat(out["computed_at"]).tzinfo is not None


def test_an_empty_window_is_all_zeros_not_a_division_error(monkeypatch):
    monkeypatch.setattr(sla, "get_settings", lambda: SimpleNamespace(AISOC_FEATURE_KPI_BAR=False))

    async def body(s):
        t = Tenant(id=uuid.uuid4(), name="Quiet", slug="quiet")
        s.add(t)
        await s.commit()
        return await sla.compute_sla_metrics(s, t.id, days=30)

    out = run(body)
    assert out["overall"] == {
        "total_alerts": 0,
        "total_breaches": 0,
        "breach_rate": 0.0,
        "mttd_avg": None,
        "mttr_avg": None,
        "mttc_avg": None,
    }


# --- POST /sla/events -------------------------------------------------------------------------------------------------------------------------------------


def _db(owned: bool = True):
    db = MagicMock()
    db.scalar = AsyncMock(return_value=uuid.uuid4() if owned else None)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


USER = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4())


def record(body, db=None):
    db = db or _db()
    asyncio.run(ep.record_sla_event(body, USER, db))
    return db


def new_event(**over):
    return ep.SLAEventCreate(**{"alert_id": uuid.uuid4(), "severity": "high", "event_type": "detected", **over})


class TestRecordEvent:
    def test_an_alert_that_is_not_this_organizations_is_a_404_and_nothing_is_stored(self):
        db = _db(owned=False)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(ep.record_sla_event(new_event(), USER, db))
        assert exc.value.status_code == 404
        db.add.assert_not_called()

    def test_a_time_with_no_zone_is_stored_as_utc(self):
        db = record(new_event(occurred_at=datetime(2026, 10, 1, 8, 30)))
        stored = db.add.call_args.args[0]
        assert stored.occurred_at.tzinfo is not None and stored.occurred_at.utcoffset() == timedelta(0)
        assert stored.occurred_at.replace(tzinfo=None) == datetime(2026, 10, 1, 8, 30)

    def test_no_time_means_now_with_a_zone(self):
        stored = record(new_event()).add.call_args.args[0]
        assert stored.occurred_at.tzinfo is not None and abs((datetime.now(UTC) - stored.occurred_at).total_seconds()) < 5

    def test_a_time_days_in_the_future_is_refused_but_a_few_minutes_of_clock_difference_is_not(self):
        with pytest.raises(HTTPException) as exc:
            record(new_event(occurred_at=datetime.now(UTC) + timedelta(days=2)))
        assert exc.value.status_code == 422
        record(new_event(occurred_at=datetime.now(UTC) + timedelta(minutes=2)))

    def test_an_unknown_severity_or_event_type_is_a_422(self):
        for bad in ({"severity": "banana"}, {"event_type": "banana"}):
            with pytest.raises(HTTPException) as exc:
                record(new_event(**bad))
            assert exc.value.status_code == 422

    def test_metadata_and_the_text_fields_are_bounded(self):
        with pytest.raises(ValidationError):
            new_event(metadata={"blob": "z" * 5000})
        with pytest.raises(ValidationError):
            new_event(severity="s" * 17)
        with pytest.raises(ValidationError):
            new_event(event_type="e" * 33)
        assert new_event(metadata={"note": "ok"}).metadata == {"note": "ok"}
