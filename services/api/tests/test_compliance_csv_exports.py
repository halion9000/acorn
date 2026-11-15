"""CSV exports of vendors, risks, controls and audits: safe cells, the right columns, and the export routes are reachable (the id routes do not swallow them). Real Postgres for the content (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL)."""

import csv
import io
import os
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import audits as au
from app.api.v1.endpoints import compliance_controls as cc
from app.api.v1.endpoints import risk_register as rr
from app.api.v1.endpoints import vendor_management as vm
from app.core.route_introspect import walk_routes
from app.db.rls import set_rls_context
from app.main import app
from app.services import csv_export
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_a_cell_that_would_run_as_a_formula_is_made_text_and_values_are_written_plainly():
    assert csv_export.cell("=SUM(A1)") == "'=SUM(A1)" and csv_export.cell("@x") == "'@x" and csv_export.cell("-1") == "'-1"
    assert csv_export.cell(None) == "" and csv_export.cell(True) == "yes" and csv_export.cell(False) == "no" and csv_export.cell(7) == "7"
    assert csv_export.cell(date(2026, 11, 14)) == "2026-11-14" and csv_export.cell(datetime(2026, 11, 14, 9, 30, tzinfo=UTC)).startswith(
        "2026-11-14T09:30"
    )
    rows = list(csv.reader(io.StringIO(csv_export.to_csv(["A", "B"], [["x, y", '"q"'], [None, "=1"]]))))
    assert rows == [["A", "B"], ["x, y", '"q"'], ["", "'=1"]]
    out = csv_export.response("f.csv", ["A"], [["1"]])
    assert out.media_type == "text/csv" and out.headers["content-disposition"] == 'attachment; filename="f.csv"'


def test_each_export_route_is_registered_before_the_id_route_that_would_swallow_it():
    paths = [path for path, route in walk_routes(app.routes) if "GET" in (route.methods or set())]
    for export, id_route in (
        ("/api/v1/compliance/vendors/export.csv", "/api/v1/compliance/vendors/{vendor_id}"),
        ("/api/v1/compliance/audits/export.csv", "/api/v1/compliance/audits/{audit_id}"),
        ("/api/v1/risk-register/export.csv", "/api/v1/risk-register/{risk_id}"),
    ):
        assert export in paths and id_route in paths and paths.index(export) < paths.index(id_route), export
    assert "/api/v1/compliance/controls/export.csv" in paths


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    acme = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:i, 'csv', :s)"), {"i": acme, "s": f"csv-{acme.hex[:8]}"})
        await conn.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2')"), {"t": acme})
    yield SimpleNamespace(
        acme=acme,
        engine=engine,
        user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com"),
        request=SimpleNamespace(client=None, headers={}),
    )
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for table in (
            "audit_requests",
            "audits",
            "risk_register_tasks",
            "risk_register_history",
            "risk_register_items",
            "vendor_history",
            "vendors",
            "compliance_enabled_frameworks",
        ):
            await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": acme})
        await conn.execute(text("delete from tenants where id = :t"), {"t": acme})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


def parse(response):
    return list(csv.reader(io.StringIO(response.body.decode())))


@needs_pg
@pytest.mark.asyncio
async def test_each_list_exports_its_rows_with_safe_cells(world):
    w = world
    await run(
        w.acme, lambda db: vm.create_vendor(vm.VendorIn(name="=Evil Vendor", risk_level="high", owner="Hal"), w.request, w.acme, db, w.user)
    )
    await run(
        w.acme,
        lambda db: rr.create_risk(
            rr.RiskIn(title="Phishing leads to a taken-over account", likelihood=4, impact=4, category="Email and phishing"),
            w.request,
            w.acme,
            db,
            w.user,
        ),
    )
    audit = await run(
        w.acme, lambda db: au.start_audit(au.AuditIn(name="SOC 2 2026", framework="SOC2", auditor="Prescient"), w.acme, db, w.user)
    )
    await run(w.acme, lambda db: au.add_request(audit.id, au.RequestIn(title="Org chart", owner="Dana"), w.acme, db, w.user))
    vendors = parse(await run(w.acme, lambda db: vm.export_vendors(w.acme, db, w.user, False)))
    assert vendors[0][0] == "Vendor" and vendors[1][0] == "'=Evil Vendor" and vendors[1][4] == "high"
    risks = parse(await run(w.acme, lambda db: rr.export_risks(w.acme, db, w.user, False)))
    assert risks[1][:2] == ["R-1", "Phishing leads to a taken-over account"] and risks[1][6:8] == ["16", "critical"]
    controls = parse(await run(w.acme, lambda db: cc.export_controls(w.acme, db, w.user, None, "not_tested", "CC1.1")))
    assert controls[0][:2] == ["Framework", "Control"] and controls[1][:2] == ["SOC2", "CC1.1"] and controls[1][4] == "not_tested"
    audits = parse(await run(w.acme, lambda db: au.export_audits(w.acme, db, w.user)))
    assert audits[1][:2] == ["SOC 2 2026", "SOC2"] and audits[1][4] == "Org chart" and audits[1][8] == "open"
