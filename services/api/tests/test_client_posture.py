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
            if "FROM cases" in text:
                return SimpleNamespace(scalar_one=lambda: 4)
            return SimpleNamespace(one=lambda: (3, 1, 2, 5))

    out = asyncio.run(cp.client_posture(owner, SimpleNamespace(tenant_id=owner, user_id=_uuid.uuid4()), DB()))
    assert (out.alerts.open, out.alerts.critical, out.alerts.high, out.alerts.without_ticket) == (3, 1, 2, 5)
    assert out.open_cases == 4
    assert [(t.vendor, t.product) for t in out.tools] == [("datto-saas", "google"), ("huntress", None)]


# ---- the checks each tool sent for a client mapped to it --------------------------------------------------------------------------------------------------


def _posture_with(monkeypatch, aliases, rows):
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
    out, queries = _posture_with(monkeypatch, [("dnsfilter", "5", "Acme")], [("threatmate", [{"key": "k", "status": "met", "evidence": "x"}])])
    assert out.tool_checks == {} and queries == []
