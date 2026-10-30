"""The second row of SOC Insights tiles, read from a REAL Postgres.

The mocked endpoint tests cannot catch a query that Postgres rejects (a JSONB test, a CASE over ``jsonb_typeof``), and the endpoint drops the whole row quietly when one query fails. This seeds a few alerts, sign-ins and a dry run
and checks every number.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services import insight_tiles as it
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database"),
]


async def _seed(conn, tenant: uuid.UUID, now: datetime) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}

    async def alert(name: str, title: str, severity: str, status: str, minutes_old: int, enrichment: dict | None = None) -> None:
        ids[name] = uuid.uuid4()
        at = now - timedelta(minutes=minutes_old)
        await conn.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, priority, event_time, first_seen, last_seen, created_at, updated_at, enrichment_data) "
                "values (:i, :t, :title, :sev, :st, 50, :at, :at, :at, :at, :at, cast(:e as jsonb))"
            ),
            {"i": ids[name], "t": tenant, "title": title, "sev": severity, "st": status, "at": at, "e": json.dumps(enrichment or {})},
        )

    await alert("breached", "Printer offline", "critical", "new", 180, {"tickets": [{"id": "1"}]})
    await alert("fresh", "Printer offline", "low", "new", 10)
    await alert("suppressed", "Printer offline", "low", "suppressed", 60)
    await alert("vendor_closed", "Other", "low", "resolved", 90, {"closed_in_vendor": {"vendor": "blumira"}})
    await alert("person_closed", "Other", "low", "resolved", 120)
    await alert("odd_tickets", "Other", "info", "new", 60, {"tickets": "not a list"})
    for score in (5.0, 1.0, None):
        await conn.execute(
            text(
                "insert into signin_events (id, tenant_id, source, source_id, user_principal, success, occurred_at, anomaly_score) "
                "values (:i, :t, 'cipp', :sid, 'amy@acme.com', true, :at, :s)"
            ),
            {"i": uuid.uuid4(), "t": tenant, "sid": uuid.uuid4().hex, "at": now - timedelta(minutes=30), "s": score},
        )
    await conn.execute(
        text(
            "insert into playbook_dry_runs (tenant_id, alert_id, playbook_id, playbook_name, created_at) values (:t, :a, 'pb1', 'Isolate host', :at)"
        ),
        {"t": tenant, "a": ids["breached"], "at": now - timedelta(minutes=5)},
    )
    return ids


async def _tenant():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tenant = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("insert into tenants (id, name, slug) values (:t, 'tiles-test', :s)"), {"t": tenant, "s": f"tiles-{tenant.hex[:10]}"}
        )
    return engine, tenant


async def _cleanup(engine, tenant: uuid.UUID) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in ("playbook_dry_runs", "signin_events", "alerts", "client_m365_checks"):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": tenant})
        await conn.execute(text("delete from tenants where id = :t"), {"t": tenant})
    await engine.dispose()


async def test_every_number_is_read_from_the_database_as_the_tile_says():
    engine, tenant = await _tenant()
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await _seed(conn, tenant, now)
        async with AsyncSession(engine) as db:
            (part,) = await it.gather_all(db, [tenant], now - timedelta(days=1), now, now - timedelta(days=2))
        assert part["open_now"] == 3, "the two new alerts and the one whose tickets field is not a list"
        assert part["sla_breached"] == 1, "only the critical alert three hours old is past its 15-minute target"
        assert part["now"]["alerts"] == 6 and part["now"]["finished"] == 3
        assert part["now"]["finished_without_person"] == 2, "suppressed and closed by the vendor; the one closed by a person is not counted"
        assert part["now"]["ticketed"] == 1, "a tickets field that is not a list counts as none and does not fail the query"
        assert part["now"]["playbook_matched"] == 1
        assert (part["now"]["signins_scored"], part["now"]["signins_unusual"]) == (2, 1)
        assert part["types"] == {"Printer offline": 3, "Other": 3}
        assert it.age_phrase(part["oldest_open"], now) == "3 hours"
        tiles = {
            t["key"]: t
            for t in it.build_tiles(
                it.merge([part]),
                now=now,
                ready=True,
                sparkline=[0.0] * 24,
                client_names={tenant: "Tiles Co"},
                sources={"total": 2, "silent": [("petra", 90)]},
            )
        }
        assert tiles["open_alerts"]["value"] == 3 and tiles["open_alerts"]["detail"] == "Oldest: 3 hours"
        assert tiles["sla_breaches"]["value"] == 1 and "1 of 3 open" in tiles["sla_breaches"]["detail"]
        assert tiles["automation_rate"]["value"] == pytest.approx(0.6667, abs=1e-3)
        assert tiles["unusual_signins"]["value"] == 1 and tiles["ticket_linkage"]["value"] == pytest.approx(0.1667, abs=1e-3)
        assert tiles["playbook_coverage"]["value"] == pytest.approx(0.1667, abs=1e-3)
        assert tiles["noisiest_clients"]["items"][0]["label"] == "Tiles Co"
        assert tiles["silent_sources"]["items"][0]["display"] == "90 min ago"
    finally:
        await _cleanup(engine, tenant)


async def test_a_tenant_with_nothing_has_tiles_that_say_so_instead_of_zero_results():
    engine, tenant = await _tenant()
    now = datetime.now(UTC)
    try:
        async with AsyncSession(engine) as db:
            (part,) = await it.gather_all(db, [tenant], now - timedelta(days=1), now, now - timedelta(days=2))
        tiles = {t["key"]: t for t in it.build_tiles(it.merge([part]), now=now, ready=True, sparkline=[], client_names=None, sources=None)}
        assert tiles["open_alerts"]["value"] == 0 and tiles["open_alerts"]["detail"] == "Oldest: none open"
        for key in ("sla_breaches", "noisy_alert_types", "automation_rate", "unusual_signins", "playbook_coverage", "ticket_linkage"):
            assert tiles[key]["has_data"] is False and tiles[key]["delta_pct"] is None, key
        assert "noisiest_clients" not in tiles and "silent_sources" not in tiles
        for key in ("leaked_credentials", "google_admins_without_2step", "google_failed_sign_ins"):
            assert tiles[key]["has_data"] is False, key
    finally:
        await _cleanup(engine, tenant)


async def test_several_tenants_are_read_together_and_a_tenant_with_its_own_targets_is_judged_by_them():
    engine, first = await _tenant()
    second = uuid.uuid4()
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, 'tiles-two', :s)"), {"t": second, "s": f"tiles-{second.hex[:10]}"}
            )
            await _seed(conn, first, now)
            await _seed(conn, second, now)
            # The second tenant allows a critical alert 1000 minutes before it is late (the default is 15): its three-hour-old critical alert is not past its target.
            await conn.execute(
                text(
                    "insert into tenant_sla_config (id, tenant_id, severity, mttd_target, mttr_target, mttc_target) values (:i, :t, 'critical', 1000, 2000, 3000)"
                ),
                {"i": uuid.uuid4(), "t": second},
            )
        async with AsyncSession(engine) as db:
            parts = await it.gather_all(db, [first, second], now - timedelta(days=1), now, now - timedelta(days=2))
        by = {p["tid"]: p for p in parts}
        assert by[first]["sla_breached"] == 1 and by[second]["sla_breached"] == 0
        merged = it.merge(parts)
        assert merged["open_now"] == 6 and merged["sla_breached"] == 1
        assert merged["now"]["alerts"] == 12 and merged["now"]["finished_without_person"] == 4 and merged["now"]["signins_unusual"] == 2
        assert merged["types"] == {"Printer offline": 6, "Other": 6}, "the top titles of both tenants added up"
        assert merged["by_tenant"] == {first: 6, second: 6}
        tiles = {
            t["key"]: t
            for t in it.build_tiles(merged, now=now, ready=True, sparkline=[], client_names={first: "One", second: "Two"}, sources=None)
        }
        assert [i["label"] for i in tiles["noisiest_clients"]["items"]] == ["One", "Two"] or [
            i["label"] for i in tiles["noisiest_clients"]["items"]
        ] == ["Two", "One"]
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            for table in ("tenant_sla_config", "playbook_dry_runs", "signin_events", "alerts"):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": second})
            await conn.execute(text("delete from tenants where id = :t"), {"t": second})
        await _cleanup(engine, first)


async def test_the_endpoint_itself_returns_the_second_row_beside_the_first_seven_on_a_real_database():
    from types import SimpleNamespace

    from app.api.v1.endpoints import insights as ins

    engine, tenant = await _tenant()
    now = datetime.now(UTC)
    ins._cache.clear()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await _seed(conn, tenant, now)
        async with AsyncSession(engine) as db:
            out = await ins.get_soc_insights(SimpleNamespace(tenant_id=tenant), db, "24h", None)
        keys = [t.key for t in out.tiles]
        assert keys[:7] == [
            "mtta",
            "mttr",
            "fp_rate",
            "alerts_per_day",
            "cases_per_day",
            "agent_cost_per_investigation",
            "analyst_hours_saved",
        ]
        assert {
            "open_alerts",
            "sla_breaches",
            "noisy_alert_types",
            "automation_rate",
            "unusual_signins",
            "playbook_coverage",
            "ticket_linkage",
        } <= set(keys)
        by = {t.key: t for t in out.tiles}
        assert by["open_alerts"].value == 3 and by["sla_breaches"].value == 1
        assert by["mtta"].has_data is False, "no alert here was ever acted on by a person: a dash, not 0.0h"
    finally:
        ins._cache.clear()
        await _cleanup(engine, tenant)


async def _seed_first_seven(conn, tenant: uuid.UUID, now: datetime, salt: int) -> None:
    """Alerts in this window and the one before, with every kind of timestamp and verdict; cases; and agent runs with costs. ``salt`` makes the two tenants differ."""
    rows = [
        # (hours old, first seen after (h) or None, resolved after (h) or None, disposition, severity)
        (1, 0.5, None, None, "high"),
        (3, 1.0, 2.0, "false_positive", "low"),
        (5, None, 4.0, "true_positive", "medium"),
        (9, 2.0, 6.5, "false_positive", "info"),
        (13, None, None, None, "low"),
        (23, 4.0, 10.0, "true_positive", "critical"),
        (30, 1.0, 3.0, "false_positive", "low"),  # the window before
        (40, None, 5.0, "true_positive", "high"),
        (47, 2.5, None, None, "medium"),
    ]
    for i, (age, seen, resolved, disposition, severity) in enumerate(rows):
        at = now - timedelta(hours=age + salt * 0.25)
        await conn.execute(
            text(
                "insert into alerts (id, tenant_id, title, severity, status, priority, event_time, first_seen, last_seen, created_at, updated_at, first_seen_at, resolved_at, disposition) "
                "values (:i, :t, :title, :sev, 'new', 50, :at, :at, :at, :at, :at, :fs, :rs, :d)"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant,
                "title": f"Alert {i}",
                "sev": severity,
                "at": at,
                "fs": at + timedelta(hours=seen) if seen is not None else None,
                "rs": at + timedelta(hours=resolved) if resolved is not None else None,
                "d": disposition,
            },
        )
    for age, status in ((2, "new"), (6, "resolved"), (20, "closed"), (33, "resolved"), (44, "new")):
        await conn.execute(
            text("insert into aisoc_cases (id, tenant_id, title, status, created_at) values (:i, :t, 'case', :s, :at)"),
            {"i": uuid.uuid4(), "t": tenant, "s": status, "at": now - timedelta(hours=age + salt)},
        )
    for age, cost in ((4, 0.25 + salt / 100), (10, 0.5), (35, 0.125)):
        run = uuid.uuid4()
        await conn.execute(
            text("insert into investigation_runs (id, tenant_id, case_id, started_at) values (:i, :t, 'c', :at)"),
            {"i": run, "t": tenant, "at": now - timedelta(hours=age)},
        )
        await conn.execute(
            text("insert into aisoc_run_costs (run_id, tenant_id, model, total_cost_usd) values (:r, :t, 'm', :c)"),
            {"r": str(run), "t": str(tenant), "c": cost},
        )


async def test_the_grouped_totals_equal_the_per_tenant_numbers_they_replace():
    """The first seven tiles used to be added up one tenant at a time (about 25 statements each); they are now a dozen grouped statements over all the tenants. Same data, same answer."""
    from app.api.v1.endpoints import insights as ins

    engine, first = await _tenant()
    second = uuid.uuid4()
    now = datetime.now(UTC)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:t, 'tiles-eq', :s)"), {"t": second, "s": f"tiles-{second.hex[:10]}"}
            )
            await _seed_first_seven(conn, first, now, 0)
            await _seed_first_seven(conn, second, now, 3)
        start, prev_start = now - timedelta(days=1), now - timedelta(days=2)
        async with AsyncSession(engine) as db:
            old = await ins._scope_totals_per_tenant(db, first, [first, second], start, now, prev_start)
        async with AsyncSession(engine) as db:
            new = await ins._scope_totals(db, first, [first, second], start, now, prev_start)
        assert set(new) == set(old), set(new) ^ set(old)
        for key, expected in old.items():
            got = new[key]
            if isinstance(expected, list):
                assert got == pytest.approx(expected, abs=1e-6), key
            elif isinstance(expected, float):
                assert got == pytest.approx(expected, abs=0.02), key  # the old way rounded each tenant's mean before weighting them
            else:
                assert got == expected, key
        assert old["alerts"] == 12 and old["prev_alerts"] == 6, "the data really covers both windows and both tenants"
        assert sum(old["alert_spark"]) == 12 and sum(old["case_spark"]) > 0 and sum(old["cost_spark"]) > 0
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from aisoc_run_costs where tenant_id = any(:t)"), {"t": [str(first), str(second)]})
            for table in ("investigation_runs", "aisoc_cases", "alerts"):
                await conn.execute(text(f"delete from {table} where tenant_id = any(:t)"), {"t": [first, second]})
            await conn.execute(text("delete from tenants where id = :t"), {"t": second})
        await _cleanup(engine, first)


async def _check(conn, tenant, source, checks):
    await conn.execute(
        text("insert into client_m365_checks (tenant_id, source, checks, refreshed_at) values (:t, :s, cast(:c as jsonb), now())"),
        {"t": tenant, "s": source, "c": json.dumps(checks)},
    )


async def test_the_check_tiles_count_the_clients_whose_tool_reported_a_failing_check_and_leave_out_the_rest():
    engine, first = await _tenant()
    second = uuid.uuid4()
    now = datetime.now(UTC)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("insert into tenants (id, name, slug) values (:t, 'tiles-two', :s)"), {"t": second, "s": f"tiles-{second.hex[:10]}"}
        )
        await _check(conn, first, "threatmate", [{"key": "threatmate_deep_dark_web", "status": "partly", "evidence": "1 finding"}])
        await _check(
            conn,
            first,
            "threatmate-google",
            [{"key": "threatmate_google_admins", "status": "met"}, {"key": "threatmate_google_failed_logins", "status": "not_met"}],
        )
        await _check(conn, second, "threatmate", [{"key": "threatmate_deep_dark_web", "status": "met"}])
    try:
        async with AsyncSession(engine) as db:
            parts = await it.gather_all(db, [first, second], now - timedelta(days=1), now, now - timedelta(days=2))
        tiles = {
            t["key"]: t
            for t in it.build_tiles(
                it.merge(parts), now=now, ready=True, sparkline=[], client_names={first: "One", second: "Two"}, sources=None
            )
        }
        assert tiles["leaked_credentials"]["value"] == 1 and tiles["leaked_credentials"]["detail"].startswith("1 of 2 clients")
        assert [i["label"] for i in tiles["leaked_credentials"]["items"]] == ["One"]
        assert tiles["google_admins_without_2step"]["value"] == 0 and tiles["google_admins_without_2step"]["has_data"] is True
        assert tiles["google_failed_sign_ins"]["value"] == 1 and tiles["google_failed_sign_ins"]["detail"].startswith("1 of 1 clients")
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from client_m365_checks where tenant_id = :t"), {"t": second})
            await conn.execute(text("delete from tenants where id = :t"), {"t": second})
        await _cleanup(engine, first)
