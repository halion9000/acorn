"""The device part of one client's posture (pure)."""

import uuid

from app.api.v1.endpoints import client_posture as ep


def test_devices_part_picks_the_clients_row_and_is_zero_for_a_client_without_devices():
    a, b = uuid.uuid4(), uuid.uuid4()
    rows = [ep.ClientRollup(client_id=a, client_name="A", devices=4, needs_attention=2, stale_agents=1, not_in_huntress=3, offline=1)]
    assert ep.devices_part(rows, a).model_dump() == {
        "devices": 4,
        "needs_attention": 2,
        "stale_agents": 1,
        "not_in_huntress": 3,
        "offline": 1,
    }
    assert ep.devices_part(rows, b).devices == 0


def test_posture_carries_the_tools_the_client_is_mapped_to():
    import uuid
    from datetime import UTC, datetime

    from app.api.v1.endpoints.client_posture import ClientPosture, PostureAlerts, PostureDevices, PostureTool

    base = {"client_id": uuid.uuid4(), "client_name": "Acme", "generated_at": datetime.now(UTC), "devices": PostureDevices(), "identity": None, "alerts": PostureAlerts(open=0, critical=0, high=0, without_ticket=0), "open_cases": 0}
    assert ClientPosture(**base).tools == []
    p = ClientPosture(**base, tools=[PostureTool(vendor="ninjaone", vendor_client_id="83", vendor_client_name="Acme")])
    assert (p.tools[0].vendor, p.tools[0].vendor_client_id) == ("ninjaone", "83")


# ---- the whole endpoint, with a client that has Datto SaaS (a 500 once: the SaaS read overwrote the alert counts) ------------------------------------------


def test_the_posture_of_a_client_in_datto_saas_still_reports_its_alert_counts_and_the_tools(monkeypatch):
    import asyncio
    import contextlib
    import uuid as _uuid
    from types import SimpleNamespace

    from app.api.v1.endpoints import client_posture as cp

    owner = _uuid.uuid4()

    async def scope(db, o, cid):
        return [owner], {}

    async def load(*a, **k):
        return []

    monkeypatch.setattr(cp, "_scope", scope)
    monkeypatch.setattr(cp, "_load_cached", load)
    monkeypatch.setattr(cp, "_master_of", lambda t: None)
    monkeypatch.setattr(cp, "acting_as_tenant", lambda db, tid: contextlib.nullcontext())

    class DB:
        async def get(self, model, key):
            return None

        async def execute(self, statement, params=None):
            text = str(statement)
            if "identity_mfa_users" in text:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
            if "client_aliases" in text:
                return SimpleNamespace(all=lambda: [("datto-saas", "494057", "Acme"), ("huntress", "5", "Acme")])
            if "client_m365_checks" in text:
                if ".source IN" in text:  # the tool-checks query (several sources at once) for a client mapped to Huntress: it has sent none
                    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
                row = SimpleNamespace(checks=[{"key": "saas_backup_google", "status": "met", "evidence": "e"}])
                return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: row))
            if "client_check_history" in text:
                return SimpleNamespace(all=lambda: [])
            if "client_check_acceptances" in text:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
            if "FROM cases" in text:
                return SimpleNamespace(scalar_one=lambda: 4)
            return SimpleNamespace(one=lambda: (3, 1, 2, 5))

    out = asyncio.run(cp.client_posture(owner, SimpleNamespace(tenant_id=owner, user_id=_uuid.uuid4()), DB()))
    assert (out.alerts.open, out.alerts.critical, out.alerts.high, out.alerts.without_ticket) == (3, 1, 2, 5)
    assert out.open_cases == 4
    assert [(t.vendor, t.product) for t in out.tools] == [("datto-saas", "google"), ("huntress", None)]


# ---- the checks each tool sent for a client mapped to it --------------------------------------------------------------------------------------------------


def _posture_with(monkeypatch, aliases, rows, history=None, accepted=None):
    """The whole posture endpoint for a client mapped as ``aliases``, where ``rows`` are the checks rows the database holds: [(source, checks)]. Returns the posture and the number of check-row queries made."""
    import asyncio
    import contextlib
    import uuid as _uuid
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from app.api.v1.endpoints import client_posture as cp

    owner = _uuid.uuid4()
    queries = []

    async def scope(db, o, cid):
        return [owner], {}

    async def load(*a, **k):
        return []

    monkeypatch.setattr(cp, "_scope", scope)
    monkeypatch.setattr(cp, "_load_cached", load)
    monkeypatch.setattr(cp, "_master_of", lambda t: None)
    monkeypatch.setattr(cp, "acting_as_tenant", lambda db, tid: contextlib.nullcontext())

    class DB:
        async def get(self, model, key):
            return None

        async def execute(self, statement, params=None):
            text = str(statement.compile(compile_kwargs={"literal_binds": True})) if hasattr(statement, "compile") else str(statement)
            if "identity_mfa_users" in text:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
            if "client_aliases" in text:
                return SimpleNamespace(all=lambda: aliases)
            if "client_m365_checks" in text:
                queries.append(text)
                asked = [src for src, _ in rows if f"'{src}'" in text]
                got = [SimpleNamespace(source=src, checks=checks, refreshed_at=datetime(2026, 10, 24, tzinfo=UTC)) for src, checks in rows if src in asked]
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: got, first=lambda: got[0] if got else None))
            if "client_check_history" in text:
                return SimpleNamespace(all=lambda: history or [])
            if "client_check_acceptances" in text:
                return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: accepted or []))
            if "FROM cases" in text:
                return SimpleNamespace(scalar_one=lambda: 0)
            return SimpleNamespace(one=lambda: (0, 0, 0, 0))

    out = asyncio.run(cp.client_posture(owner, SimpleNamespace(tenant_id=owner, user_id=_uuid.uuid4()), DB()))
    return out, queries


def test_checks_are_shown_per_tool_and_only_for_tools_the_client_is_mapped_to(monkeypatch):
    rows = [
        ("threatmate", [{"key": "threatmate_patching", "status": "not_met", "evidence": "1 of 3"}, {"key": "", "status": "met", "evidence": "dropped: no key"}, "not a dict"]),
        ("liongard", [{"key": "liongard_edr_coverage", "status": "met", "evidence": "2 of 2"}]),
        ("itglue", [{"key": "itglue_domain_expiry", "status": "partly", "evidence": "1 expires soon"}]),
    ]
    out, queries = _posture_with(monkeypatch, [("threatmate", "11", "Acme"), ("liongard", "7", "Acme")], rows)
    assert list(out.tool_checks) == ["liongard", "threatmate"], "IT Glue sent checks but the client is not mapped to it"
    assert [(c.key, c.status) for c in out.tool_checks["threatmate"].checks] == [("threatmate_patching", "not_met")]
    assert out.tool_checks["liongard"].checks[0].evidence == "2 of 2"
    assert out.tool_checks["threatmate"].refreshed_at is not None
    assert len(queries) == 1, "all the tools' rows are read in one query"
    assert "'itglue'" not in queries[0]


def test_cipps_extra_checks_are_read_from_their_own_source_when_the_client_is_mapped_to_cipp(monkeypatch):
    rows = [("cipp-health", [{"key": "cipp_licences", "status": "partly", "evidence": "3 unused"}]), ("cipp", [{"key": "baseline_x", "status": "met", "evidence": "the Microsoft 365 baseline is not a tool check"}])]
    out, _ = _posture_with(monkeypatch, [("cipp", "tenant-1", "Acme")], rows)
    assert list(out.tool_checks) == ["cipp-health"]


def test_a_client_mapped_to_no_checking_tool_reads_no_check_rows_at_all(monkeypatch):
    out, queries = _posture_with(monkeypatch, [("screenconnect", "5", "Acme")], [("threatmate", [{"key": "k", "status": "met", "evidence": "x"}])])
    assert out.tool_checks == {} and queries == []


# ---- since when, accepted checks, and how the sweeps are doing -----------------------------------------------------------------------------------------------


def test_each_check_says_since_when_it_has_had_its_status_and_whether_a_person_accepted_it(monkeypatch):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    changed = datetime(2026, 10, 20, tzinfo=UTC)
    live = SimpleNamespace(key="threatmate_patching", reason="Client will replace the machines in January", accepted_at=datetime(2026, 10, 21, tzinfo=UTC), expires_at=datetime.now(UTC) + timedelta(days=30))
    gone = SimpleNamespace(key="threatmate_security_score", reason="old", accepted_at=datetime(2026, 1, 1, tzinfo=UTC), expires_at=datetime(2026, 2, 1, tzinfo=UTC))
    rows = [("threatmate", [{"key": "threatmate_patching", "status": "not_met", "evidence": "x"}, {"key": "threatmate_security_score", "status": "not_met", "evidence": "y"}, {"key": "threatmate_end_of_life", "status": "met", "evidence": "z"}])]
    out, _ = _posture_with(monkeypatch, [("threatmate", "11", "Acme")], rows, history=[("threatmate_patching", changed)], accepted=[live, gone])
    by = {c.key: c for c in out.tool_checks["threatmate"].checks}
    assert by["threatmate_patching"].since == changed
    assert by["threatmate_patching"].accepted is not None and by["threatmate_patching"].accepted.reason.startswith("Client will replace")
    assert by["threatmate_security_score"].accepted is None, "an acceptance that has run out no longer counts"
    assert by["threatmate_end_of_life"].since is None and by["threatmate_end_of_life"].accepted is None


def test_a_check_carries_the_list_behind_it_and_a_malformed_list_is_ignored(monkeypatch):
    rows = [
        (
            "ninjaone",
            [
                {"key": "ninjaone_antivirus", "status": "not_met", "evidence": "x", "items": ["PC-1: none installed", "", 7, "PC-2: switched off"]},
                {"key": "ninjaone_patching", "status": "partly", "evidence": "y", "items": "not a list"},
                {"key": "ninjaone_unsupported_os", "status": "met", "evidence": "z"},
            ],
        )
    ]
    out, _ = _posture_with(monkeypatch, [("ninjaone", "1", "Acme")], rows)
    by = {c.key: c for c in out.tool_checks["ninjaone"].checks}
    assert by["ninjaone_antivirus"].items == ["PC-1: none installed", "PC-2: switched off"]
    assert by["ninjaone_patching"].items == [] and by["ninjaone_unsupported_os"].items == []


def test_a_report_may_carry_up_to_forty_short_items_per_check_and_no_more():
    import pytest
    from app.api.v1.endpoints.client_review import M365CheckIn
    from pydantic import ValidationError

    assert M365CheckIn(key="k", status="met").items == []
    assert len(M365CheckIn(key="k", status="met", items=["x" * 120] * 40).items) == 40
    with pytest.raises(ValidationError):
        M365CheckIn(key="k", status="met", items=["x"] * 41)
    with pytest.raises(ValidationError):
        M365CheckIn(key="k", status="met", items=["x" * 121])


def test_a_sweeps_health_is_stale_after_48_hours_then_failed_partly_or_ok():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    recent, old = now - timedelta(hours=2), now - timedelta(hours=49)
    assert ep.sweep_health(10, 0, recent, now) == "ok"
    assert ep.sweep_health(10, 2, recent, now) == "partly"
    assert ep.sweep_health(0, 3, recent, now) == "failed"
    assert ep.sweep_health(0, 0, recent, now) == "ok", "a pass with nothing due is not a failure"
    assert ep.sweep_health(10, 0, old, now) == "stale", "an old pass is stale even if it went well"


def test_accepting_a_check_needs_a_reason_a_sensible_key_and_a_bounded_end_date(monkeypatch):
    import asyncio
    import uuid as _uuid
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    owner = _uuid.uuid4()
    user = SimpleNamespace(tenant_id=owner, user_id=_uuid.uuid4())

    class DB:
        async def execute(self, *a, **k):  # never reached: every case below is refused first
            raise AssertionError("the database was touched")

    def call(key, reason, days=None):
        return asyncio.run(ep.accept_check(owner, key, ep.AcceptIn(reason=reason, expires_in_days=days), user, DB()))

    for key, reason, days in (("k", "  ", None), ("k", "x" * 401, None), ("bad key!", "fine reason", None), ("k", "fine reason", 0), ("k", "fine reason", ep.MAX_ACCEPT_DAYS + 1)):
        with pytest.raises(HTTPException) as e:
            call(key, reason, days)
        assert e.value.status_code == 422, (key, reason, days)
