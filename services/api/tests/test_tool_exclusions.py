"""A client can be marked as not using a tool: its machines are never counted as missing from it, its checks for the tool vanish from the posture pages, and a worsened check raises no alert."""

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from app.api.v1.endpoints import client_posture as cp
from app.api.v1.endpoints.devices import DeviceOut, DeviceSourceOut, is_missing_from, rollup_of
from app.services import check_alerts
from app.services import tool_exclusions as tx
from app.services.client_review import device_facts
from fastapi import HTTPException

NOW = datetime(2026, 11, 3, tzinfo=UTC)
OWNER, CLIENT = uuid.uuid4(), uuid.uuid4()


def device(excluded=(), vendors=("ninjaone",), tenant=CLIENT, os="Windows 11"):
    return DeviceOut(
        id=uuid.uuid4(),
        tenant_id=tenant,
        client_name="Acme",
        hostname=f"PC-{uuid.uuid4().hex[:4]}",
        os=os,
        last_seen=NOW,
        first_seen=NOW,
        sources=[DeviceSourceOut(vendor=v, name="x", last_seen=NOW, details={}, last_checkin=NOW, stale=False) for v in vendors],
        excluded_tools=list(excluded),
    )


# ---- the settings -------------------------------------------------------------------------------------------------------------------------------------------


def test_the_four_tools_asked_for_can_be_excluded():
    assert {"huntress", "screenconnect", "addigy", "fieldeffect"} <= set(tx.EXCLUDABLE)


def test_a_list_is_stored_unique_and_sorted_and_an_unknown_tool_is_refused_by_name():
    assert tx.normalize(["Huntress", "addigy", "huntress"]) == ["addigy", "huntress"]
    with pytest.raises(ValueError, match="windows"):
        tx.normalize(["huntress", "windows"])
    with pytest.raises(ValueError):
        tx.normalize([""])


def test_reading_ignores_anything_that_is_not_a_known_tool_so_a_hand_edit_cannot_widen_it():
    assert tx.of_settings({"tool_exclusions": ["huntress", "bogus", 5, None]}) == frozenset({"huntress"})
    assert tx.of_settings({"tool_exclusions": "huntress"}) == frozenset()
    assert tx.of_settings(None) == frozenset() and tx.of_settings({}) == frozenset()


def test_setting_keeps_the_other_settings_and_an_empty_list_removes_the_key():
    s = {"hidden": True, "devices": {"master_vendor": "ninjaone"}}
    out = tx.with_exclusions(s, ["huntress"])
    assert out == {"hidden": True, "devices": {"master_vendor": "ninjaone"}, "tool_exclusions": ["huntress"]} and "tool_exclusions" not in s
    assert tx.with_exclusions(out, []) == s


def test_a_tool_checks_source_maps_to_its_tool_so_threatmate_google_belongs_to_threatmate():
    assert tx.check_is_excluded("threatmate-google", frozenset({"threatmate"}))
    assert tx.check_is_excluded("huntress", frozenset({"huntress"}))
    assert not tx.check_is_excluded("huntress", frozenset({"screenconnect"})) and not tx.check_is_excluded("huntress", frozenset())


# ---- the devices --------------------------------------------------------------------------------------------------------------------------------------------


def test_an_excluded_tool_is_never_missing_for_that_client_but_others_still_are():
    d = device(excluded=["huntress"])
    assert not is_missing_from(d, "huntress")
    assert is_missing_from(d, "screenconnect")
    assert is_missing_from(device(), "huntress")  # another client with no exclusion is unchanged


def test_each_of_the_four_is_honoured_including_addigy_on_a_mac_and_field_effect():
    mac = device(excluded=["addigy", "fieldeffect", "screenconnect", "huntress"], os="macOS")
    assert [is_missing_from(mac, t) for t in ("addigy", "fieldeffect", "screenconnect", "huntress")] == [False] * 4
    assert is_missing_from(device(os="macOS"), "addigy") and is_missing_from(device(), "fieldeffect")


def test_the_roll_up_counts_nothing_missing_from_huntress_for_a_client_that_does_not_use_it():
    rows = rollup_of([device(excluded=["huntress"]), device(excluded=["huntress"]), device(tenant=OWNER)])
    by = {r.client_id: r.not_in_huntress for r in rows}
    assert by[CLIENT] == 0 and by[OWNER] == 1


def test_the_client_review_marks_an_excluded_tool_instead_of_counting_a_gap():
    facts = device_facts([device(excluded=["huntress"]), device(excluded=["huntress"])], stale_agents=0, offline=0)
    huntress = next(c for c in facts.coverage if c.tool == "huntress")
    assert (huntress.excluded, huntress.of, huntress.percent) == (True, 0, None)
    assert all(not c.excluded for c in facts.coverage if c.tool != "huntress")


# ---- the posture checks and alerts -------------------------------------------------------------------------------------------------------------------------


class FakeDb:
    def __init__(self, settings=None, known_client=True):
        self.settings, self.known_client, self.added, self.committed = settings, known_client, [], 0
        self.tenant = NS(settings=settings)
        self.queries = []

    async def execute(self, stmt, *a, **k):
        text = str(stmt)
        self.queries.append(text)
        if "tenants.parent_tenant_id" in text:
            return NS(scalar_one_or_none=lambda: CLIENT if self.known_client else None)
        if "FROM alerts" in text:
            return NS(scalar_one_or_none=lambda: None)  # no alert for this check and day yet
        return NS(scalar_one_or_none=lambda: self.settings, scalars=lambda: NS(all=lambda: []), all=lambda: [])

    async def get(self, model, key):
        return self.tenant

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed += 1


def test_a_worsened_check_of_an_excluded_tool_raises_no_alert_and_another_tool_still_does():
    changes = [{"key": "huntress_protection", "status": "not_met", "previous_status": "met", "evidence": "x"}]
    assert asyncio.run(check_alerts.raise_alerts(FakeDb({"tool_exclusions": ["huntress"]}), CLIENT, "huntress", changes, NOW)) == 0
    other = FakeDb({"tool_exclusions": ["screenconnect"]})
    assert asyncio.run(check_alerts.raise_alerts(other, CLIENT, "huntress", changes, NOW)) == 1 and len(other.added) == 1


def test_the_clients_posture_page_reads_no_checks_for_an_excluded_tool():
    db = FakeDb({"tool_exclusions": ["huntress"]})
    assert asyncio.run(cp._all_tool_checks(db, OWNER, CLIENT, [("huntress", "1", "Acme")])) == {}
    assert not any("client_m365_checks" in q for q in db.queries)  # not even asked for
    other = FakeDb({"tool_exclusions": ["screenconnect"]})
    asyncio.run(cp._all_tool_checks(other, OWNER, CLIENT, [("huntress", "1", "Acme")]))
    assert any("client_m365_checks" in q for q in other.queries)  # a client that excludes another tool still has its Huntress checks read


# ---- the endpoints ------------------------------------------------------------------------------------------------------------------------------------------


def user():
    return NS(tenant_id=OWNER, user_id=uuid.uuid4(), email="o@example.com")


def put(db, tools, client=CLIENT):
    return asyncio.run(cp.put_tool_exclusions(client, cp.ToolExclusionsIn(tools=tools), user(), db))


@pytest.fixture
def audited(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(cp, "emit_audit", audit)
    return audit


def test_choosing_tools_stores_them_on_the_client_audits_the_change_and_drops_the_caches(audited, monkeypatch):
    from app.api.v1.endpoints import devices

    forgot = []
    monkeypatch.setattr(devices, "forget_loaded", lambda: forgot.append(1))
    db = FakeDb({"hidden": True})
    out = put(db, ["Huntress", "screenconnect", "addigy", "fieldeffect"])
    assert out.tools == ["addigy", "fieldeffect", "huntress", "screenconnect"]
    assert db.tenant.settings == {"hidden": True, "tool_exclusions": out.tools}
    (call,) = audited.await_args_list
    assert (
        call.kwargs["action"] == "posture:tool_exclusions_changed"
        and call.kwargs["changes"]["before"] == []
        and call.kwargs["changes"]["after"] == out.tools
    )
    assert forgot == [1]


def test_repeating_the_same_choice_is_not_audited_again(audited):
    put(FakeDb({"tool_exclusions": ["huntress"]}), ["huntress"])
    audited.assert_not_awaited()


def test_an_empty_list_clears_them_and_is_audited(audited):
    db = FakeDb({"tool_exclusions": ["huntress"]})
    assert put(db, []).tools == [] and "tool_exclusions" not in db.tenant.settings
    assert audited.await_args.kwargs["changes"]["before"] == ["huntress"]


def test_an_unknown_tool_the_managing_company_and_a_stranger_client_are_refused(audited):
    with pytest.raises(HTTPException) as e:
        put(FakeDb({}), ["huntress", "notatool"])
    assert e.value.status_code == 422 and "notatool" in e.value.detail
    with pytest.raises(HTTPException) as e:
        put(FakeDb({}), ["huntress"], client=OWNER)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException) as e:
        put(FakeDb({}, known_client=False), ["huntress"])
    assert e.value.status_code == 404
    audited.assert_not_awaited()


# ---- the reverse: marked as not used, but it is there ----------------------------------------------------------------------------------------------------


def test_a_tool_marked_as_not_used_that_reports_devices_is_a_finding_naming_how_many():
    found = tx.detect_excluded_but_present(CLIENT, "Acme", frozenset({"huntress", "addigy"}), {"huntress": 12}, set(), NOW)
    assert [f.title for f in found] == ["huntress is marked as not used for Acme, but it is there"]
    f = found[0]
    assert (f.severity, f.rule_id, f.key) == ("medium", tx.RULE_ID, "huntress:2026-11")
    assert "reports 12 devices" in f.summary and "untick it" in f.summary
    assert ("Devices reporting", "12") in f.fields and ("Linked to an organization", "no") in f.fields


def test_being_linked_to_an_organization_of_the_tool_counts_even_with_no_devices_and_both_are_said():
    only_linked = tx.detect_excluded_but_present(CLIENT, "Acme", frozenset({"huntress"}), {}, {"huntress"}, NOW)
    assert (
        len(only_linked) == 1
        and "is linked to one of its organizations" in only_linked[0].summary
        and "reports" not in only_linked[0].summary
    )
    both = tx.detect_excluded_but_present(CLIENT, "Acme", frozenset({"huntress"}), {"huntress": 1}, {"huntress"}, NOW)[0]
    assert "reports 1 device and is linked to one of its organizations" in both.summary


def test_nothing_is_raised_for_an_excluded_tool_that_is_really_absent_or_for_a_tool_that_is_not_excluded():
    assert tx.detect_excluded_but_present(CLIENT, "Acme", frozenset({"huntress"}), {}, set(), NOW) == []
    assert tx.detect_excluded_but_present(CLIENT, "Acme", frozenset(), {"huntress": 5}, {"huntress"}, NOW) == []
    assert (
        tx.detect_excluded_but_present(CLIENT, "Acme", frozenset({"huntress"}), {"screenconnect": 5}, {"screenconnect"}, NOW) == []
    )  # another tool's devices are not this tool's


def test_it_comes_back_each_month_and_not_each_day():
    june = tx.detect_excluded_but_present(
        CLIENT, "Acme", frozenset({"huntress"}), {"huntress": 1}, set(), datetime(2026, 6, 3, tzinfo=UTC)
    )[0].key
    later_june = tx.detect_excluded_but_present(
        CLIENT, "Acme", frozenset({"huntress"}), {"huntress": 1}, set(), datetime(2026, 6, 28, tzinfo=UTC)
    )[0].key
    july = tx.detect_excluded_but_present(
        CLIENT, "Acme", frozenset({"huntress"}), {"huntress": 1}, set(), datetime(2026, 7, 1, tzinfo=UTC)
    )[0].key
    assert june == later_june == "huntress:2026-06" and july == "huntress:2026-07"


class RunDb:
    """Answers the runner's reads by statement text: the client, its links to tools, and how many devices each excluded tool reports."""

    def __init__(self, settings, counts=(), links=()):
        self.settings, self.counts, self.links, self.writes = settings, list(counts), list(links), []

    async def execute(self, stmt, *a, **k):
        text = str(stmt)
        if text.lstrip().upper().startswith("INSERT"):
            self.writes.append(stmt)
            return NS(rowcount=1)
        if "FROM tenants" in text:
            return NS(all=lambda: [NS(id=CLIENT, name="Acme", settings=self.settings)])
        if "FROM client_aliases" in text:
            return NS(scalars=lambda: NS(all=lambda: self.links))
        if "FROM device_sources" in text:
            return NS(all=lambda: self.counts)
        return NS(all=lambda: [])

    def begin_nested(self):
        class C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

        return C()


@pytest.fixture
def no_rls(monkeypatch):
    import contextlib

    from app.db import rls_scope

    @contextlib.asynccontextmanager
    async def noop(*a, **k):
        yield

    monkeypatch.setattr(rls_scope, "acting_as_tenant", noop)


def test_the_runner_raises_one_alert_in_the_clients_tenant_for_a_tool_that_is_excluded_and_reporting(no_rls):
    from sqlalchemy.dialects import postgresql

    db = RunDb({"tool_exclusions": ["huntress", "addigy"]}, counts=[("huntress", 3)])
    assert asyncio.run(tx.run_excluded_present(db, OWNER, [CLIENT], NOW)) == 1
    c = db.writes[0].compile(dialect=postgresql.dialect())
    assert "ON CONFLICT (id) DO NOTHING" in str(c)
    assert (
        c.params["tenant_id"] == CLIENT
        and c.params["title"] == "huntress is marked as not used for Acme, but it is there"
        and c.params["category"] == "posture"
    )


def test_the_runner_raises_nothing_for_a_client_with_no_exclusions_or_no_such_devices(no_rls):
    assert asyncio.run(tx.run_excluded_present(RunDb({}, counts=[("huntress", 3)]), OWNER, [CLIENT], NOW)) == 0
    quiet = RunDb({"tool_exclusions": ["huntress"]})
    assert asyncio.run(tx.run_excluded_present(quiet, OWNER, [CLIENT], NOW)) == 0 and quiet.writes == []


def test_a_failure_in_the_check_never_fails_the_sync_that_called_it(no_rls):
    class Broken(RunDb):
        async def execute(self, *a, **k):
            raise RuntimeError("down")

    assert asyncio.run(tx.run_excluded_present(Broken({}), OWNER, [CLIENT], NOW)) == 0


def test_marking_a_tool_as_not_used_while_it_reports_devices_checks_straight_away(audited, monkeypatch):
    from app.api.v1.endpoints import devices

    monkeypatch.setattr(devices, "forget_loaded", lambda: None)
    called = []

    async def fake_run(db, owner, tenants, now=None):
        called.append((owner, tenants))
        return 1

    monkeypatch.setattr(tx, "run_excluded_present", fake_run)
    put(FakeDb({}), ["huntress"])
    assert called == [(OWNER, [CLIENT])]
    called.clear()
    put(FakeDb({"tool_exclusions": ["huntress"]}), ["huntress"])  # no change: not checked again here
    put(FakeDb({"tool_exclusions": ["huntress"]}), [])  # nothing excluded now: nothing to check
    assert called == []
