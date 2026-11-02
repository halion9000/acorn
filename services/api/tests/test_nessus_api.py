"""Uploaded Nessus scans: matching hosts to devices, storing a scan per client, the upload/list/detail/delete routes."""

import asyncio
import contextlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.api.v1.endpoints import nessus as ep
from app.db.database import Base
from app.models.nessus import NessusFinding, NessusScan
from app.models.tenant import Tenant
from app.services.nessus_import import Host, parse_nessus
from app.services.nessus_store import DeviceRef, match_device
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, NessusScan, NessusFinding)]


def item(plugin, name, severity, port=443, cves=(), exploit="false", cvss="7.5"):
    cve_xml = "".join(f"<cve>{c}</cve>" for c in cves)
    return (
        f'<ReportItem port="{port}" svc_name="www" protocol="tcp" severity="{severity}" pluginID="{plugin}" pluginName="{name}"><synopsis>S{plugin}</synopsis><solution>Fix{plugin}</solution>'
        f"<cvss3_base_score>{cvss}</cvss3_base_score>{cve_xml}<exploit_available>{exploit}</exploit_available></ReportItem>"
    )


def host(name, items, ip=None, fqdn=None):
    return f'<ReportHost name="{name}"><HostProperties><tag name="host-ip">{ip or name}</tag><tag name="host-fqdn">{fqdn or name}</tag></HostProperties>{"".join(items)}</ReportHost>'


def doc(*hosts, report="Monthly"):
    return f'<?xml version="1.0"?><NessusClientData_v2><Report name="{report}">{"".join(hosts)}</Report></NessusClientData_v2>'.encode()


A, B = uuid.uuid4(), uuid.uuid4()
DEVICES = [DeviceRef(A, "ACME-PC01", ("10.0.0.5",)), DeviceRef(B, "ACME-PC02.corp.example", ("10.0.0.6",))]


def parsed_host(name="x", ip=None, fqdn=None):
    return Host(name=name, ip=ip, fqdn=fqdn, os=None)


class TestMatching:
    def test_by_name_in_any_form_and_case(self):
        assert match_device(parsed_host("acme-pc01"), DEVICES) == A
        assert match_device(parsed_host("10.9.9.9", fqdn="ACME-PC01.corp.example"), DEVICES) == A
        assert match_device(parsed_host("acme-pc02"), DEVICES) == B  # the device is stored with its domain, the scan without

    def test_by_address_when_the_name_says_nothing(self):
        assert match_device(parsed_host("10.0.0.6", ip="10.0.0.6"), DEVICES) == B

    def test_a_name_wins_over_an_address(self):
        assert match_device(parsed_host("acme-pc01", ip="10.0.0.6"), DEVICES) == A

    def test_unknown_hosts_and_ambiguous_ones_are_not_guessed(self):
        assert match_device(parsed_host("stranger", ip="10.1.1.1"), DEVICES) is None
        twins = [DeviceRef(uuid.uuid4(), "pc01"), DeviceRef(uuid.uuid4(), "PC01.other.example")]
        assert match_device(parsed_host("pc01"), twins) is None
        shared = [DeviceRef(uuid.uuid4(), "a", ("10.0.0.9",)), DeviceRef(uuid.uuid4(), "b", ("10.0.0.9",))]
        assert match_device(parsed_host("10.0.0.9", ip="10.0.0.9"), shared) is None


class TestAmbiguousNamesAreNotRescuedByAnAddress:
    def test_two_machines_with_the_same_name_stay_unmatched_even_when_the_address_would_pick_one(self):
        one, two = uuid.uuid4(), uuid.uuid4()
        twins = [DeviceRef(one, "pc01", ("10.0.0.50",)), DeviceRef(two, "PC01.other.example", ("10.0.0.51",))]
        assert match_device(parsed_host("pc01", ip="10.0.0.50"), twins) is None  # the name is ambiguous: the address is not used to break the tie


# ── the routes ──
@pytest.fixture(autouse=True)
def stand_ins(monkeypatch):
    @contextlib.asynccontextmanager
    async def plain(_db):
        yield

    monkeypatch.setattr(ep, "cross_tenant_reads", plain)  # the row-level-security switch is Postgres-only
    monkeypatch.setattr(ep, "emit_audit", AsyncMock())

    async def devices(_db, _tenant):
        return DEVICES

    monkeypatch.setattr(ep, "load_devices", devices)


def run(coro_fn):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as c:
            await c.run_sync(lambda conn: Base.metadata.create_all(conn, tables=TABLES))
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            try:
                return await coro_fn(s)
            finally:
                await engine.dispose()

    return asyncio.run(main())


async def tenant(s, name, parent=None):
    t = Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(), parent_tenant_id=parent)
    s.add(t)
    await s.flush()
    return t


def user(owner):
    return SimpleNamespace(tenant_id=owner.id, user_id=uuid.uuid4(), email="hal@goliveoak.com")


def request(data: bytes, length=None):
    async def body():
        return data

    return SimpleNamespace(headers={"content-length": str(len(data) if length is None else length)}, body=body)


FILE = doc(
    host("ACME-PC01", [item("1", "SMB signing off", 2), item("2", "Old TLS", 3, cves=["CVE-2020-1"], exploit="true", cvss="9.8"), item("3", "Info only", 0)], ip="10.0.0.5"),
    host("10.0.0.77", [item("4", "Critical thing", 4, cvss="10.0"), item("5", "Low thing", 1)]),
)


async def upload(s, owner, client, data=FILE, **kw):
    return await ep.upload_scan(request(data), user(owner), s, client.id, name=kw.get("name"), description=kw.get("description"), notes=kw.get("notes"), scan_type=kw.get("scan_type"))


def test_an_upload_is_stored_for_the_client_with_counts_and_matches_and_audited():
    async def body(s):
        owner = await tenant(s, "Owner")
        acme = await tenant(s, "Acme", owner.id)
        await s.commit()
        out = await upload(s, owner, acme, description="Monthly LAN")
        rows = (await s.execute(select(NessusFinding))).scalars().all()
        return out, acme.id, rows

    out, acme_id, rows = run(body)
    assert (out.client_id, out.client_name, out.name, out.scan_type, out.description) == (acme_id, "Acme", "Monthly", "lan", "Monthly LAN")
    assert (out.hosts, out.matched_hosts, out.critical, out.high, out.medium, out.low) == (2, 1, 1, 1, 1, 1)  # the informational finding is not kept
    assert len(rows) == 4 and {r.device_id for r in rows if r.host_name == "ACME-PC01"} == {A}
    assert all(r.device_id is None for r in rows if r.host_name == "10.0.0.77")
    ep.emit_audit.assert_awaited()
    assert ep.emit_audit.await_args.kwargs["action"] == "nessus:scan_uploaded"


def test_the_scan_type_can_be_chosen_over_the_guess():
    async def body(s):
        owner = await tenant(s, "Owner")
        await s.commit()
        return (await upload(s, owner, owner, scan_type="wan")).scan_type

    assert run(body) == "wan"


def test_a_file_that_is_not_a_nessus_export_is_refused_and_nothing_is_stored():
    async def body(s):
        owner = await tenant(s, "Owner")
        await s.commit()
        with pytest.raises(HTTPException) as e:
            await upload(s, owner, owner, data=b"<html/>")
        return e.value.status_code, e.value.detail, (await s.execute(select(NessusScan))).scalars().all()

    code, detail, scans = run(body)
    assert code == 422 and "not a Nessus v2" in detail and scans == []


def test_an_oversized_upload_is_refused_before_it_is_read(monkeypatch):
    async def body(s):
        owner = await tenant(s, "Owner")
        await s.commit()
        with pytest.raises(HTTPException) as e:
            await ep.upload_scan(request(b"x", length=ep.MAX_BYTES + 1), user(owner), s, owner.id)
        return e.value.status_code

    assert run(body) == 413


def test_nobody_uploads_for_a_client_that_is_not_theirs():
    async def body(s):
        mine, theirs = await tenant(s, "Mine"), await tenant(s, "Theirs")
        stranger = await tenant(s, "Their Client", theirs.id)
        await s.commit()
        with pytest.raises(HTTPException) as e:
            await upload(s, mine, stranger)
        return e.value.status_code

    assert run(body) == 404


def test_the_list_and_detail_show_only_the_owners_scans_worst_findings_first_with_filters_and_pages():
    async def body(s):
        owner, other = await tenant(s, "Owner"), await tenant(s, "Other")
        acme = await tenant(s, "Acme", owner.id)
        their_client = await tenant(s, "Theirs", other.id)
        await s.commit()
        mine = await upload(s, owner, acme)
        await upload(s, other, their_client, name="not mine")
        listed = await ep.list_scans(user(owner), s, client_id=None)
        detail = await ep.scan_detail(mine.id, user(owner), s, severity=None, host=None, page=1, page_size=3)
        crit = await ep.scan_detail(mine.id, user(owner), s, severity="critical", host=None, page=1, page_size=50)
        by_host = await ep.scan_detail(mine.id, user(owner), s, severity=None, host="acme-pc", page=1, page_size=50)
        with pytest.raises(HTTPException) as e:
            await ep.scan_detail(uuid.uuid4(), user(owner), s, severity=None, host=None, page=1, page_size=50)
        return listed, detail, crit, by_host, e.value.status_code

    listed, detail, crit, by_host, code = run(body)
    assert [x.name for x in listed] == ["Monthly"] and code == 404
    assert [f.severity for f in detail.findings] == ["critical", "high", "medium"] and detail.total_findings == 4 and detail.pages == 2
    assert detail.findings[1].exploit is True and detail.findings[1].cves == ["CVE-2020-1"]
    assert [f.name for f in crit.findings] == ["Critical thing"]
    assert {f.host_name for f in by_host.findings} == {"ACME-PC01"}


def test_deleting_a_scan_removes_it_and_its_findings_and_is_audited():
    async def body(s):
        owner = await tenant(s, "Owner")
        await s.commit()
        scan = await upload(s, owner, owner)
        await ep.delete_scan(scan.id, user(owner), s)
        return (await s.execute(select(NessusScan))).scalars().all(), ep.emit_audit.await_args.kwargs["action"]

    scans, action = run(body)
    assert scans == [] and action == "nessus:scan_deleted"
