"""The approvals CORE says are waiting for the owner reach the notification bell: CORE's status report carries them, A.C.O.R.N keeps them for 20 minutes, a guarded route serves them."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import health, inbox_core_feed
from app.services import core_approvals
from pydantic import ValidationError

TENANT = uuid.uuid4()
ITEMS = [
    {"role": "jax", "summary": "Close case 7", "days_left": 5},
    {"role": "cipher", "summary": "Escalate alert 12", "days_left": 1},
]


def run(coro):
    return asyncio.run(coro)


class TestTheStore:
    def test_what_was_reported_comes_back_oldest_waiting_first_and_expires_in_twenty_minutes(self, revocation_store):
        run(core_approvals.remember(TENANT, ITEMS))
        found = run(core_approvals.recall(TENANT))
        assert [i["summary"] for i in found["items"]] == ["Escalate alert 12", "Close case 7"], "the one with the fewest days left is first"
        assert found["reported_at"]
        assert revocation_store.ttls[f"aisoc:core-approvals:{TENANT}"] == 20 * 60

    def test_an_empty_report_means_nothing_is_waiting_and_replaces_the_old_list(self, revocation_store):
        run(core_approvals.remember(TENANT, ITEMS))
        run(core_approvals.remember(TENANT, []))
        assert run(core_approvals.recall(TENANT))["items"] == []

    def test_another_client_tenant_never_sees_it(self, revocation_store):
        run(core_approvals.remember(TENANT, ITEMS))
        assert run(core_approvals.recall(uuid.uuid4())) is None

    def test_a_redis_outage_neither_fails_the_report_nor_invents_a_list(self, revocation_store):
        revocation_store.down = True
        run(core_approvals.remember(TENANT, ITEMS))
        assert run(core_approvals.recall(TENANT)) is None

    def test_an_unreadable_value_is_ignored(self, revocation_store):
        revocation_store.data[f"aisoc:core-approvals:{TENANT}"] = "{not json"
        assert run(core_approvals.recall(TENANT)) is None


class TestTheReport:
    def test_the_status_report_accepts_the_list_and_an_older_core_without_it(self):
        with_list = inbox_core_feed.StatusReport(sources=[], approvals=ITEMS)
        assert [a.role for a in with_list.approvals] == ["jax", "cipher"]
        assert inbox_core_feed.StatusReport(sources=[]).approvals is None
        assert inbox_core_feed.StatusReport(sources=[], approvals=[]).approvals == []

    @pytest.mark.parametrize(
        "bad",
        [
            {"role": "x" * 41, "summary": "s", "days_left": 1},
            {"role": "r", "summary": "s" * 201, "days_left": 1},
            {"role": "r", "summary": "s", "days_left": -1},
            {"role": "r", "summary": "s", "days_left": 31},
        ],
    )
    def test_oversized_or_nonsense_entries_are_refused(self, bad):
        with pytest.raises(ValidationError):
            inbox_core_feed.StatusReport(sources=[], approvals=[bad])
        with pytest.raises(ValidationError):
            inbox_core_feed.StatusReport(sources=[], approvals=[ITEMS[0]] * 51)

    def test_the_status_route_stores_the_list_for_the_tokens_tenant_and_leaves_it_alone_when_absent(self, monkeypatch, revocation_store):
        async def verify(db, token):
            return TENANT

        async def nothing(*a, **k):
            return 0

        class Db:
            async def commit(self):
                return None

            async def rollback(self):
                return None

        for name in (
            "adopt_tenant",
            "apply_report",
            "snapshot_children_throttled",
            "open_cases_for_new_alerts",
            "close_finished_cases",
            "sync_iocs_throttled",
        ):
            monkeypatch.setattr(inbox_core_feed, name, nothing)
        monkeypatch.setattr(inbox_core_feed, "_verify_core_feed_token", verify)
        run(inbox_core_feed.report_core_feed_status("tok", inbox_core_feed.StatusReport(sources=[], approvals=ITEMS), Db()))
        assert [i["role"] for i in run(core_approvals.recall(TENANT))["items"]] == ["cipher", "jax"]
        run(inbox_core_feed.report_core_feed_status("tok", inbox_core_feed.StatusReport(sources=[]), Db()))
        assert len(run(core_approvals.recall(TENANT))["items"]) == 2, "an older CORE that sends no list changes nothing"


class TestTheRoute:
    def test_the_bell_route_returns_the_callers_own_tenant_only(self, revocation_store):
        run(core_approvals.remember(TENANT, ITEMS))
        mine = run(health.core_approvals_waiting(SimpleNamespace(tenant_id=TENANT)))
        assert mine["reported"] is True and [i["role"] for i in mine["items"]] == ["cipher", "jax"]
        assert json.dumps(mine["items"][0], sort_keys=True) == json.dumps(
            {"role": "cipher", "summary": "Escalate alert 12", "days_left": 1}, sort_keys=True
        )
        other = run(health.core_approvals_waiting(SimpleNamespace(tenant_id=uuid.uuid4())))
        assert other == {"reported": False, "reported_at": None, "items": []}
