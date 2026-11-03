"""The remote tools page: the inventory numbers, which devices a blocked tool raises an alert for, what a CORE report stores and removes, and who may decide."""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from app.api.v1.endpoints import remote_tools as ep
from app.models.remote_tool import ALL_CLIENTS
from app.services import remote_tools as rt
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
OWNER, A, B = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def seen(tenant, host, tool, version=None, days_ago=0, path=None, instance=""):
    return NS(
        tenant_id=tenant, hostname=host, tool_key=tool, version=version, first_seen=NOW - timedelta(days=30), last_seen=NOW - timedelta(days=days_ago), hostname_key=rt.host_key(host), vendor="ninjaone",
        install_path=path, program=None, instance_id=instance,
    )


def scan(tenant, n, days_ago=0):
    return NS(tenant_id=tenant, devices_scanned=n, scanned_at=NOW - timedelta(days=days_ago))


# ---- the numbers -------------------------------------------------------------------------------------------------------------------------------------------


def test_the_inventory_counts_clients_devices_and_what_is_decided_per_tool():
    rows = [
        seen(A, "PC-1", "anydesk", "8.0"), seen(A, "PC-2", "anydesk"), seen(B, "PC-9", "anydesk"),
        seen(A, "PC-1.acme.local", "teamviewer"), seen(B, "PC-9", "screenconnect", days_ago=3),
    ]
    rules = {("anydesk", None): "blocked", ("anydesk", B): "allowed", ("screenconnect", None): "allowed"}
    inv = ep.build_inventory(rows, rules, [scan(A, 40), scan(B, 10, days_ago=2)])
    by = {t.key: t for t in inv.tools}
    assert (inv.tools_found, inv.devices_scanned) == (3, 50)
    assert inv.last_scanned == NOW
    assert inv.devices_with_tools == 3  # PC-1, PC-2 of A and PC-9 of B (PC-1 twice is one device)
    a = by["anydesk"]
    assert (a.clients, a.devices, a.verdict, a.client_rules) == (2, 3, "blocked", 1)
    assert (a.blocked_devices, a.allowed_devices, a.unreviewed_devices) == (2, 1, 0)  # B runs it on purpose
    assert by["teamviewer"].verdict == "unreviewed" and by["teamviewer"].unreviewed_devices == 1
    assert by["screenconnect"].last_seen == NOW - timedelta(days=3)
    assert inv.blocked_devices == 2


def test_blocked_tools_come_first_then_the_most_widespread():
    rows = [seen(A, f"PC-{i}", "teamviewer") for i in range(5)] + [seen(A, "PC-1", "anydesk")]
    inv = ep.build_inventory(rows, {("anydesk", None): "blocked"}, [])
    assert [t.key for t in inv.tools] == ["anydesk", "teamviewer"]


def test_an_unknown_tool_key_in_storage_is_ignored_and_nothing_stored_is_an_empty_page():
    assert ep.build_inventory([seen(A, "PC-1", "not_in_catalog")], {}, []).tools_found == 0
    empty = ep.build_inventory([], {}, [])
    assert (empty.tools_found, empty.devices_scanned, empty.last_scanned, empty.tools) == (0, 0, None, [])


# ---- the alerts --------------------------------------------------------------------------------------------------------------------------------------------


def test_a_blocked_tool_is_a_finding_for_each_device_in_the_clients_own_tenant_and_other_verdicts_are_not():
    rows = [seen(A, "PC-1", "anydesk", "8.0"), seen(A, "PC-2", "teamviewer"), seen(B, "PC-9", "anydesk")]
    rules = {("anydesk", None): "blocked", ("anydesk", B): "allowed", ("teamviewer", None): "allowed"}
    found = rt.blocked_findings(rows, rules, NOW)
    assert [(t, f.title) for t, f in found] == [(A, "Blocked remote tool AnyDesk found on PC-1")]
    f = found[0][1]
    assert (f.severity, f.technique, f.key) == ("high", "T1219", "anydesk:pc-1")
    assert ("Version", "8.0") in f.fields and "nobody should be running it" in f.summary


def test_the_finding_key_is_the_device_and_tool_so_a_domain_suffix_or_case_does_not_make_a_second_alert():
    a = rt.blocked_findings([seen(A, "PC-1.acme.local", "anydesk")], {("anydesk", None): "blocked"}, NOW)[0][1].key
    b = rt.blocked_findings([seen(A, "pc-1", "anydesk")], {("anydesk", None): "blocked"}, NOW)[0][1].key
    assert a == b == "anydesk:pc-1"


# ---- a fake database ---------------------------------------------------------------------------------------------------------------------------------------


class FakeDb:
    def __init__(self, alias=None, children=(), held=(), rules=(), clients=None, owner_settings=None):
        self.owner_settings = owner_settings
        self.owner_tenant = NS(settings=owner_settings)
        self.alias, self.children, self.held, self.rules_rows = alias, list(children), list(held), list(rules)
        self.clients = clients if clients is not None else {c: f"Client {i}" for i, c in enumerate(self.children)}
        self.writes, self.deleted = [], []

    async def execute(self, stmt, *a, **k):
        text = str(stmt)
        if text.lstrip().upper().startswith("SELECT"):
            if "FROM client_aliases" in text:
                return NS(scalar_one_or_none=lambda: self.alias)
            if "tenants.parent_tenant_id" in text and "tenants.name" in text:
                return NS(all=lambda: [NS(id=c, name=n) for c, n in self.clients.items()])
            if "FROM tenants" in text:
                return NS(scalars=lambda: NS(all=lambda: self.children))
            if "FROM device_remote_tools" in text:
                return NS(scalars=lambda: NS(all=lambda: self.held))
            if "FROM remote_tool_rules" in text:
                one = self.rules_rows[0] if self.rules_rows else None
                return NS(scalars=lambda: NS(all=lambda: self.rules_rows), scalar_one_or_none=lambda: one)
            return NS(scalars=lambda: NS(all=lambda: []), scalar_one_or_none=lambda: None, all=lambda: [])
        if text.lstrip().upper().startswith("DELETE"):
            self.deleted.append(stmt)
        else:
            self.writes.append(stmt)
        return NS(rowcount=1)

    async def get(self, model, key):
        return self.owner_tenant

    def begin_nested(self):
        return ep._Nothing()

    async def flush(self):
        return None

    async def commit(self):
        return None


@pytest.fixture(autouse=True)
def _no_row_level_security(monkeypatch):
    @contextlib.asynccontextmanager
    async def noop(*a, **k):
        yield

    monkeypatch.setattr(ep, "acting_as_tenant", noop)
    monkeypatch.setattr(ep, "cross_tenant_reads", noop)


def sql(stmt):
    c = stmt.compile(dialect=postgresql.dialect())
    return str(c), c.params


def alerts(db):
    return [(s, p) for s, p in (sql(w) for w in db.writes) if "INSERT INTO alerts" in s]


def report(items, scanned=10, client="123"):
    return ep.RemoteToolsReport(vendor="ninjaone", vendor_client_id=client, devices_scanned=scanned, items=[ep.FoundIn(**i) for i in items])


def run(db, rep, owner=OWNER):
    return asyncio.run(ep.apply_report(db, owner, rep, NOW))


MAPPED = NS(child_tenant_id=A, ignored=False)


# ---- a report from CORE ------------------------------------------------------------------------------------------------------------------------------------


def test_a_report_stores_each_tool_once_per_device_and_stamps_the_scan():
    db = FakeDb(alias=MAPPED, children=[A])
    out = run(db, report([{"hostname": "PC-1", "tool_key": "anydesk", "version": "8.0"}, {"hostname": "pc-1.acme.local", "tool_key": "anydesk"}, {"hostname": "PC-2", "tool_key": "teamviewer"}]))
    assert (out.stored, out.removed, out.unmapped, out.alerts_raised) == (2, 0, False, 0)
    inserts = [sql(w) for w in db.writes if "INSERT INTO device_remote_tools" in str(w)]
    assert {p["hostname_key"] for _, p in inserts} == {"pc-1", "pc-2"} and all(p["tenant_id"] == A for _, p in inserts)
    assert all("ON CONFLICT (tenant_id, hostname_key, tool_key, instance_id) DO UPDATE" in s for s, _ in inserts)
    (scan_sql, scan_params), = [sql(w) for w in db.writes if "INSERT INTO remote_tool_scans" in str(w)]
    assert scan_params["devices_scanned"] == 10 and scan_params["tenant_id"] == A


def test_what_a_full_scan_no_longer_finds_is_removed_but_an_empty_scan_removes_nothing():
    held = [NS(hostname_key="pc-old", tool_key="anydesk", tenant_id=A, hostname="PC-OLD", version=None, last_seen=NOW, first_seen=NOW)]
    db = FakeDb(alias=MAPPED, children=[A], held=held)
    out = run(db, report([{"hostname": "PC-1", "tool_key": "anydesk"}]))
    assert out.removed == 1 and len(db.deleted) == 1
    db2 = FakeDb(alias=MAPPED, children=[A], held=held)
    out2 = run(db2, report([], scanned=0))
    assert out2.removed == 0 and db2.deleted == []


def test_a_report_for_a_client_not_mapped_yet_or_ignored_stores_nothing():
    for alias in (None, NS(child_tenant_id=None, ignored=False), NS(child_tenant_id=A, ignored=True), NS(child_tenant_id=B, ignored=False)):
        db = FakeDb(alias=alias, children=[A])
        out = run(db, report([{"hostname": "PC-1", "tool_key": "anydesk"}]))
        assert out.unmapped is True and out.stored == 0 and db.writes == [], alias


def test_an_unknown_tool_in_a_report_is_counted_and_not_stored():
    db = FakeDb(alias=MAPPED, children=[A])
    out = run(db, report([{"hostname": "PC-1", "tool_key": "made_up"}, {"hostname": "PC-1", "tool_key": "anydesk"}]))
    assert (out.stored, out.unknown_tools) == (1, 1)


def test_no_alert_unless_the_tool_is_blocked_and_then_one_in_the_clients_tenant_naming_the_device():
    row = seen(A, "PC-1", "anydesk", "8.0")
    quiet = FakeDb(alias=MAPPED, children=[A], held=[row])
    assert run(quiet, report([{"hostname": "PC-1", "tool_key": "anydesk"}])).alerts_raised == 0 and alerts(quiet) == []
    rule = NS(tool_key="anydesk", client_id=ALL_CLIENTS, verdict="blocked")
    loud = FakeDb(alias=MAPPED, children=[A], held=[row], rules=[rule])
    out = run(loud, report([{"hostname": "PC-1", "tool_key": "anydesk"}]))
    (text, p), = alerts(loud)
    assert out.alerts_raised == 1 and "ON CONFLICT (id) DO NOTHING" in text
    assert p["tenant_id"] == A and p["title"] == "Blocked remote tool AnyDesk found on PC-1" and p["category"] == "remote_access" and p["severity"] == "high"


def test_the_managing_companys_own_devices_are_stored_under_itself_when_no_client_id_is_given():
    db = FakeDb(children=[A])
    out = run(db, report([{"hostname": "SRV-1", "tool_key": "putty"}], client=None))
    assert out.stored == 1 and sql(db.writes[0])[1]["tenant_id"] == OWNER


# ---- deciding ----------------------------------------------------------------------------------------------------------------------------------------------


def user():
    return NS(tenant_id=OWNER, user_id=uuid.uuid4(), email="o@example.com")


def decide(db, tool, verdict, client=None, note=None):
    return asyncio.run(ep.set_verdict(tool, ep.VerdictIn(verdict=verdict, client_id=client, note=note), user(), db))


@pytest.fixture
def audited(monkeypatch):
    audit = AsyncMock()
    monkeypatch.setattr(ep, "emit_audit", audit)
    return audit


def test_blocking_a_tool_for_everyone_saves_the_rule_audits_it_and_raises_an_alert_for_each_device_it_is_already_on(audited, monkeypatch):
    rows = [seen(A, "PC-1", "anydesk"), seen(B, "PC-9", "anydesk")]
    monkeypatch.setattr(ep, "_sightings", AsyncMock(return_value=rows))
    db = FakeDb(children=[A, B])
    out = decide(db, "anydesk", "blocked", note="  never   allowed ")
    assert (out.verdict, out.client_id) == ("blocked", None)
    rule_sql, rule = [sql(w) for w in db.writes if "INSERT INTO remote_tool_rules" in str(w)][0]
    assert rule["client_id"] == ALL_CLIENTS and rule["verdict"] == "blocked" and rule["note"] == "never allowed" and "ON CONFLICT (tenant_id, tool_key, client_id) DO UPDATE" in rule_sql
    assert audited.await_args.kwargs["action"] == "remote_tool:verdict_changed" and audited.await_args.kwargs["changes"]["after"] == "blocked"


def test_allowing_for_one_client_stores_that_clients_own_rule_and_raises_nothing(audited):
    db = FakeDb(children=[A, B])
    out = decide(db, "anydesk", "allowed", client=A)
    assert out.alerts_raised == 0 and alerts(db) == []
    assert [sql(w)[1]["client_id"] for w in db.writes if "INSERT INTO remote_tool_rules" in str(w)] == [A]


def test_unreviewed_for_one_client_removes_its_own_rule_so_it_follows_everyone_again(audited):
    db = FakeDb(children=[A], rules=[NS(verdict="allowed")])
    decide(db, "anydesk", "unreviewed", client=A)
    assert len(db.deleted) == 1 and not [w for w in db.writes if "INSERT INTO remote_tool_rules" in str(w)]


def test_repeating_the_same_decision_is_not_audited_again(audited):
    decide(FakeDb(children=[A], rules=[NS(verdict="allowed")]), "putty", "allowed")
    audited.assert_not_awaited()


def test_an_unknown_tool_a_stranger_client_and_a_bad_verdict_are_refused(audited):
    with pytest.raises(HTTPException) as e:
        decide(FakeDb(children=[A]), "nope", "blocked")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        decide(FakeDb(children=[A]), "anydesk", "blocked", client=uuid.uuid4())
    assert e.value.status_code == 404
    with pytest.raises(ValueError):
        ep.VerdictIn(verdict="maybe")
    audited.assert_not_awaited()


def test_only_someone_who_manages_clients_may_decide_and_reading_needs_alerts_read():
    from app.core.route_introspect import required_permissions as perms

    def required_permissions(route):
        return set(perms(route))

    routes = {(m, r.path): r for r in ep.router.routes for m in getattr(r, "methods", [])}
    assert required_permissions(routes[("PUT", "/remote-tools/tools/{tool_key}/verdict")]) == {"mssp:manage"}
    for path in ("/remote-tools/inventory", "/remote-tools/catalog", "/remote-tools/tools/{tool_key}/devices"):
        assert required_permissions(routes[("GET", path)]) == {"alerts:read"}


# ---- where it is installed, and whose server it connects to ------------------------------------------------------------------------------------------------

OURS = "798cebdb8316a8ff"
THEIRS = "1111222233334444"
SC_PATH = "C:\\Program Files (x86)\\ScreenConnect Client ({})"


def test_the_instance_id_is_read_from_the_program_name_or_the_folder_and_only_for_tools_that_have_one():
    assert rt.instance_of("screenconnect", "ScreenConnect Client (798cebdb8316a8ff)", None) == OURS
    assert rt.instance_of("screenconnect", "ScreenConnect Client", SC_PATH.format("798CEBDB8316A8FF")) == OURS  # the folder, any case
    assert rt.instance_of("screenconnect", "ScreenConnect Client", None) == ""
    assert rt.instance_of("screenconnect", "ScreenConnect Client (not-an-id-at-all)", "C:\\Windows\\Temp\\0123456789abcdef0") == ""  # 17 hex digits is not a 16-digit id
    assert rt.instance_of("anydesk", "AnyDesk (798cebdb8316a8ff)") == ""


def test_identifiers_are_stored_clean_and_a_bad_one_is_refused_by_name():
    assert rt.normalize_instance_ids([THEIRS, OURS, " " + OURS.upper() + " "]) == sorted([OURS, THEIRS])
    assert rt.normalize_instance_ids([" 798CEBDB8316A8FF ", OURS]) == [OURS]
    with pytest.raises(ValueError, match="zzz"):
        rt.normalize_instance_ids([OURS, "zzz"])
    with pytest.raises(ValueError):
        rt.normalize_instance_ids(["abc"])  # too short to mean anything


def test_the_owners_identifiers_are_read_from_the_settings_and_junk_in_them_is_ignored():
    assert rt.trusted_instances({"remote_tool_instances": {"screenconnect": [OURS, "bad", 5], "nope": [OURS]}}) == {"screenconnect": [OURS]}
    assert rt.trusted_instances(None) == {} and rt.trusted_instances({"remote_tool_instances": "x"}) == {}
    s = rt.with_trusted_instances({"hidden": True}, "screenconnect", [OURS])
    assert s == {"hidden": True, "remote_tool_instances": {"screenconnect": [OURS]}}
    assert rt.with_trusted_instances(s, "screenconnect", []) == {"hidden": True}


def test_an_install_for_another_server_is_a_critical_finding_naming_the_path_and_yours_is_not():
    rows = [
        seen(A, "PC-1", "screenconnect", path=SC_PATH.format(OURS), instance=OURS),
        seen(A, "PC-1", "screenconnect", path=SC_PATH.format(THEIRS), instance=THEIRS),
        seen(A, "PC-2", "screenconnect", instance=""),  # no identifier could be read: not judged
        seen(A, "PC-3", "anydesk"),
    ]
    found = rt.foreign_findings(rows, {"screenconnect": [OURS]}, NOW)
    assert [(t, f.title) for t, f in found] == [(A, f"ScreenConnect for another server ({THEIRS}) found on PC-1")]
    f = found[0][1]
    assert (f.severity, f.rule_id, f.key) == ("critical", rt.FOREIGN_RULE_ID, f"screenconnect:pc-1:{THEIRS}")
    assert ("Installed at", SC_PATH.format(THEIRS)) in f.fields and ("Your identifiers", OURS) in f.fields


def test_nothing_is_judged_until_the_owner_has_said_which_identifiers_are_theirs():
    rows = [seen(A, "PC-1", "screenconnect", instance=THEIRS)]
    assert rt.foreign_findings(rows, {}, NOW) == []
    assert rt.foreign_findings(rows, {"anydesk": [OURS]}, NOW) == []


def test_a_blocked_tool_installed_twice_on_a_device_is_one_alert_and_it_says_where():
    rows = [seen(A, "PC-1", "screenconnect", path="C:\\a", instance=OURS), seen(A, "PC-1", "screenconnect", path="C:\\b", instance=THEIRS)]
    found = rt.blocked_findings(rows, {("screenconnect", None): "blocked"}, NOW)
    assert len(found) == 1 and any(k == "Installed at" and v in ("C:\\a", "C:\\b") for k, v in found[0][1].fields)


def test_the_inventory_counts_a_device_once_however_many_installs_and_counts_the_other_servers_installs():
    rows = [seen(A, "PC-1", "screenconnect", instance=OURS), seen(A, "PC-1", "screenconnect", instance=THEIRS), seen(A, "PC-2", "screenconnect", instance=OURS)]
    inv = ep.build_inventory(rows, {}, [], {"screenconnect": [OURS]})
    t = inv.tools[0]
    assert (t.devices, t.has_instances, t.trusted_instances, t.foreign_installs) == (2, True, [OURS], 1)
    plain = ep.build_inventory([seen(A, "PC-1", "anydesk")], {}, [])
    assert (plain.tools[0].has_instances, plain.tools[0].foreign_installs) == (False, 0)


def test_a_report_keeps_each_install_apart_with_its_path_and_program():
    db = FakeDb(alias=MAPPED, children=[A])
    out = run(
        db,
        report(
            [
                {"hostname": "PC-1", "tool_key": "screenconnect", "program": f"ScreenConnect Client ({OURS})", "path": SC_PATH.format(OURS)},
                {"hostname": "PC-1", "tool_key": "screenconnect", "program": f"ScreenConnect Client ({THEIRS})", "path": SC_PATH.format(THEIRS)},
                {"hostname": "pc-1.acme.local", "tool_key": "screenconnect", "program": f"ScreenConnect Client ({THEIRS})", "path": SC_PATH.format(THEIRS)},
            ]
        ),
    )
    assert out.stored == 2  # the same install listed twice is one
    inserts = [sql(w) for w in db.writes if "INSERT INTO device_remote_tools" in str(w)]
    assert sorted(p["instance_id"] for _, p in inserts) == sorted([OURS, THEIRS])
    assert {p["install_path"] for _, p in inserts} == {SC_PATH.format(OURS), SC_PATH.format(THEIRS)}
    assert all("ON CONFLICT (tenant_id, hostname_key, tool_key, instance_id) DO UPDATE" in t for t, _ in inserts)


def test_a_scan_that_no_longer_finds_one_of_two_installs_removes_only_that_one():
    held = [
        NS(hostname_key="pc-1", tool_key="screenconnect", instance_id=OURS, tenant_id=A, hostname="PC-1", version=None, last_seen=NOW, first_seen=NOW),
        NS(hostname_key="pc-1", tool_key="screenconnect", instance_id=THEIRS, tenant_id=A, hostname="PC-1", version=None, last_seen=NOW, first_seen=NOW),
    ]
    db = FakeDb(alias=MAPPED, children=[A], held=held)
    out = run(db, report([{"hostname": "PC-1", "tool_key": "screenconnect", "program": f"ScreenConnect Client ({OURS})"}]))
    assert out.removed == 1 and len(db.deleted) == 1
    assert THEIRS in str(db.deleted[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_a_report_raises_a_critical_alert_for_another_servers_install_once_the_owner_has_set_theirs():
    row = seen(A, "PC-1", "screenconnect", path=SC_PATH.format(THEIRS), instance=THEIRS)
    quiet = FakeDb(alias=MAPPED, children=[A], held=[row])
    assert run(quiet, report([{"hostname": "PC-1", "tool_key": "screenconnect", "program": f"ScreenConnect Client ({THEIRS})"}])).alerts_raised == 0
    loud = FakeDb(alias=MAPPED, children=[A], held=[row], owner_settings={"remote_tool_instances": {"screenconnect": [OURS]}})
    out = run(loud, report([{"hostname": "PC-1", "tool_key": "screenconnect", "program": f"ScreenConnect Client ({THEIRS})"}]))
    (text, p), = alerts(loud)
    assert out.alerts_raised == 1 and p["severity"] == "critical" and p["tenant_id"] == A and THEIRS in p["title"]
    assert "foreign-server" in p["tags"]


def set_instances(db, tool, ids):
    return asyncio.run(ep.set_instances(tool, ep.InstancesIn(ids=ids), user(), db))


def test_saving_your_identifiers_stores_them_on_the_company_audits_it_and_alerts_for_installs_already_found(audited, monkeypatch):
    rows = [seen(A, "PC-1", "screenconnect", path=SC_PATH.format(THEIRS), instance=THEIRS), seen(A, "PC-2", "screenconnect", instance=OURS)]
    monkeypatch.setattr(ep, "_sightings", AsyncMock(return_value=rows))
    db = FakeDb(children=[A], owner_settings={"hidden": False})
    out = set_instances(db, "screenconnect", ["798CEBDB8316A8FF"])
    assert (out.ids, out.alerts_raised) == ([OURS], 1)
    assert db.owner_tenant.settings == {"hidden": False, "remote_tool_instances": {"screenconnect": [OURS]}}
    assert audited.await_args.kwargs["action"] == "remote_tool:instances_changed" and audited.await_args.kwargs["changes"]["after"] == [OURS]


def test_a_tool_with_no_server_identifier_an_unknown_tool_and_a_bad_identifier_are_refused(audited):
    with pytest.raises(HTTPException) as e:
        set_instances(FakeDb(children=[A]), "anydesk", [OURS])
    assert e.value.status_code == 422 and "no identifiers to set" in e.value.detail
    with pytest.raises(HTTPException) as e:
        set_instances(FakeDb(children=[A]), "nope", [OURS])
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        set_instances(FakeDb(children=[A]), "screenconnect", ["zzz"])
    assert e.value.status_code == 422 and "zzz" in e.value.detail
    audited.assert_not_awaited()


def test_repeating_the_same_identifiers_is_not_audited_again(audited, monkeypatch):
    monkeypatch.setattr(ep, "_sightings", AsyncMock(return_value=[]))
    set_instances(FakeDb(children=[A], owner_settings={"remote_tool_instances": {"screenconnect": [OURS]}}), "screenconnect", [OURS])
    audited.assert_not_awaited()


def test_only_someone_who_manages_clients_may_set_the_identifiers():
    from app.core.route_introspect import required_permissions as perms

    routes = {(m, r.path): r for r in ep.router.routes for m in getattr(r, "methods", [])}
    assert set(perms(routes[("PUT", "/remote-tools/tools/{tool_key}/instances")])) == {"mssp:manage"}
