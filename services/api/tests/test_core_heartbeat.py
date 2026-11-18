"""CORE's status report carries its commit, uptime and feed passes; A.C.O.R.N keeps them for 20 minutes and a guarded route serves them."""

import asyncio
import uuid
from types import SimpleNamespace

from app.api.v1.endpoints import health, inbox_core_feed
from app.services import core_heartbeat
from pydantic import ValidationError

TENANT = uuid.uuid4()


def run(coro):
    return asyncio.run(coro)


class TestTheStore:
    def test_the_values_come_back_and_expire_in_twenty_minutes(self, revocation_store):
        run(core_heartbeat.remember(TENANT, "d4c7178", 3600, 12))
        got = run(core_heartbeat.recall(TENANT))
        assert (got["commit"], got["uptime_seconds"], got["sweeps"]) == ("d4c7178", 3600, 12) and got["reported_at"]
        assert revocation_store.ttls[f"aisoc:core-heartbeat:{TENANT}"] == 20 * 60

    def test_a_newer_report_replaces_the_older_and_another_tenant_sees_nothing(self, revocation_store):
        run(core_heartbeat.remember(TENANT, "aaa", 10, 1))
        run(core_heartbeat.remember(TENANT, "bbb", 20, 2))
        assert run(core_heartbeat.recall(TENANT))["commit"] == "bbb"
        assert run(core_heartbeat.recall(uuid.uuid4())) is None

    def test_a_negative_number_or_a_long_commit_is_cut_down_and_a_redis_outage_fails_nothing(self, revocation_store):
        run(core_heartbeat.remember(TENANT, "c" * 100, -5, -1))
        got = run(core_heartbeat.recall(TENANT))
        assert len(got["commit"]) == 40 and got["uptime_seconds"] == 0 and got["sweeps"] == 0
        revocation_store.down = True
        run(core_heartbeat.remember(TENANT, "x", 1, 1))
        assert run(core_heartbeat.recall(TENANT)) is None

    def test_an_unreadable_value_is_ignored(self, revocation_store):
        revocation_store.data[f"aisoc:core-heartbeat:{TENANT}"] = "{not json"
        assert run(core_heartbeat.recall(TENANT)) is None


class TestTheReportAndTheRoute:
    def test_the_status_report_takes_the_values_and_an_older_core_may_leave_them_out(self):
        ok = inbox_core_feed.StatusReport(sources=[], core={"commit": "d4c7178", "uptime_seconds": 5, "sweeps": 2})
        assert ok.core.commit == "d4c7178"
        assert inbox_core_feed.StatusReport(sources=[]).core is None
        for bad in ({"commit": "x" * 41, "uptime_seconds": 1, "sweeps": 1}, {"commit": "x", "uptime_seconds": -1, "sweeps": 1}):
            try:
                inbox_core_feed.StatusReport(sources=[], core=bad)
            except ValidationError:
                continue
            raise AssertionError(f"accepted {bad}")

    def test_the_route_serves_what_was_reported_for_the_callers_tenant_only(self, revocation_store):
        run(core_heartbeat.remember(TENANT, "d4c7178", 90, 3))
        mine = run(health.core_heartbeat(SimpleNamespace(tenant_id=TENANT)))
        assert mine["reported"] is True and mine["commit"] == "d4c7178" and mine["uptime_seconds"] == 90 and mine["sweeps"] == 3
        other = run(health.core_heartbeat(SimpleNamespace(tenant_id=uuid.uuid4())))
        assert other == {"reported": False, "reported_at": None, "commit": None, "uptime_seconds": None, "sweeps": None}
