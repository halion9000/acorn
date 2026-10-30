"""An alert is raised the day a watched check gets worse, never for a first report and never twice."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services import check_alerts as ca
from app.services.check_history import changes
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def check(key, status, evidence=""):
    return {"key": key, "status": status, "evidence": evidence}


def specs(previous, new, source="threatmate-google"):
    return ca.alerts_for_changes(changes(previous, new, source), source, NOW)


def test_a_watched_check_going_from_fine_to_failing_raises_one_alert_with_what_was_seen():
    out = specs([check("threatmate_google_admins", "met")], [check("threatmate_google_admins", "not_met", "2 super admins have no 2-Step")])
    assert len(out) == 1
    assert (
        out[0]["severity"] == "high"
        and "2 super admins have no 2-Step" in out[0]["description"]
        and "was met, now not met" in out[0]["description"]
    )
    assert out[0]["idempotency_key"] == "check:threatmate-google:threatmate_google_admins:2026-10-29:not_met"


def test_the_first_report_of_a_check_and_an_unchanged_or_improving_check_raise_nothing():
    assert specs(None, [check("threatmate_google_admins", "not_met")]) == []
    assert specs([], [check("threatmate_google_admins", "not_met")]) == []
    assert specs([check("threatmate_google_admins", "not_met")], [check("threatmate_google_admins", "not_met")]) == []
    assert specs([check("threatmate_google_admins", "not_met")], [check("threatmate_google_admins", "met")]) == []


def test_a_check_nobody_watches_raises_nothing_and_partly_only_matters_for_the_dark_web():
    assert specs([check("threatmate_patching", "met")], [check("threatmate_patching", "not_met")]) == []
    assert specs([check("threatmate_google_admins", "met")], [check("threatmate_google_admins", "partly")]) == []
    dark = specs([check("threatmate_deep_dark_web", "met")], [check("threatmate_deep_dark_web", "partly", "1 open finding")], "threatmate")
    assert [a["key"] for a in dark] == ["threatmate_deep_dark_web"]


def test_worsened_needs_a_known_previous_status():
    assert ca.worsened(None, "not_met", "not_met") is False
    assert ca.worsened("met", "unknown", "not_met") is False
    assert ca.worsened("partly", "not_met", "not_met") is True
    assert ca.worsened("not_met", "partly", "partly") is False


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


@pg
@pytest.mark.asyncio
async def test_the_alert_is_stored_once_for_the_same_check_day_and_status():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:t, 'ca', :s)"), {"t": tid, "s": f"ca-{tid.hex[:10]}"})
    try:
        change = changes(
            [check("threatmate_google_admins", "met")], [check("threatmate_google_admins", "not_met", "x")], "threatmate-google"
        )
        async with AsyncSession(engine) as db:
            assert await ca.raise_alerts(db, tid, "threatmate-google", change, NOW) == 1
            await db.commit()
            assert await ca.raise_alerts(db, tid, "threatmate-google", change, NOW) == 0, "the same report again adds nothing"
            await db.commit()
            row = (
                await db.execute(text("select title, severity, status, connector_type, tags from alerts where tenant_id = :t"), {"t": tid})
            ).all()
            assert (
                len(row) == 1
                and row[0][1] == "high"
                and row[0][2] == "new"
                and row[0][3] == "aisoc-checks"
                and "posture-change" in row[0][4]
            )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from alerts where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()


class _Failing:
    def __init__(self, title, since, key=None, owner=None):
        self.title, self.failing_since, self.key, self.owner = title, since, key, owner


def test_a_secureframe_test_failing_for_two_weeks_raises_one_alert_naming_its_owner():
    old = _Failing("MFA on all accounts", datetime(2026, 10, 1, tzinfo=UTC), key="mfa-1", owner="Dale")
    out = ca.secureframe_alerts([old], NOW)
    assert len(out) == 1 and out[0]["title"] == "Secureframe test failing for 28 days: MFA on all accounts"
    assert "Owner: Dale." in out[0]["description"] and out[0]["idempotency_key"] == "secureframe:mfa-1:14d"
    assert "It has no owner." in ca.secureframe_alerts([_Failing("x", datetime(2026, 9, 1, tzinfo=UTC))], NOW)[0]["description"]


def test_a_young_or_undated_failing_test_raises_nothing():
    assert ca.secureframe_alerts([_Failing("new", datetime(2026, 10, 20, tzinfo=UTC)), _Failing("undated", None)], NOW) == []
    assert ca.secureframe_alerts([_Failing("edge", datetime(2026, 10, 15, 12, tzinfo=UTC))], NOW) != []


def d(days_ago):
    return NOW.date() - timedelta(days=days_ago)


def test_a_score_that_fell_ten_points_in_a_week_raises_one_alert_per_week():
    spec = ca.score_drop_spec(d(0), [(d(8), 90), (d(3), 85), (d(0), 78)])
    assert spec is not None and spec["title"] == "Check score fell 12 points in 8 days (now 78)"
    assert spec["idempotency_key"] == "score-drop:2026-W44"


def test_a_small_drop_a_rise_no_old_enough_score_or_no_score_today_raises_nothing():
    assert ca.score_drop_spec(d(0), [(d(8), 90), (d(0), 82)]) is None
    assert ca.score_drop_spec(d(0), [(d(8), 70), (d(0), 90)]) is None
    assert ca.score_drop_spec(d(0), [(d(3), 95), (d(0), 60)]) is None, "three days is not a week"
    assert ca.score_drop_spec(d(0), [(d(20), 95), (d(0), 60)]) is None, "twenty days back is out of range"
    assert ca.score_drop_spec(d(0), [(d(8), 90), (d(1), 60)]) is None, "no score today"
    assert ca.score_drop_spec(d(0), [(d(8), None), (d(0), 50)]) is None


def test_a_surge_of_failed_google_sign_ins_raises_a_medium_alert():
    out = specs(
        [check("threatmate_google_failed_logins", "met")], [check("threatmate_google_failed_logins", "not_met", "63 failed sign-ins")]
    )
    assert [(a["key"], a["severity"]) for a in out] == [("threatmate_google_failed_logins", "medium")]
