"""The trust center and audits: the small rules, then both on a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database)."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import audits as au
from app.api.v1.endpoints import trust_center as tc
from app.db.rls import set_rls_context
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


def test_a_document_link_must_be_web_address_and_a_framework_line_is_worked_out_from_its_controls():
    docs = tc.clean_documents([tc.DocumentIn(name=" SOC 2 report ", url=" https://example.com/soc2.pdf ")])
    assert docs == [{"name": "SOC 2 report", "url": "https://example.com/soc2.pdf"}]
    with pytest.raises(ValueError):
        tc.clean_documents([tc.DocumentIn(name="Bad one", url="javascript:alert(1)")])
    line = tc.framework_lines(["SOC2", "HIPAA"], {"SOC2": ["healthy", "healthy", "unhealthy", "not_tested"]})
    assert (line[0].controls, line[0].healthy, line[0].percent_healthy) == (4, 2, 50)
    assert (line[1].controls, line[1].percent_healthy) == (0, None)


def test_an_audit_link_is_checked_and_blank_means_none():
    assert au.check_link("  https://x.example/y ") == "https://x.example/y"
    assert au.check_link("  ") is None and au.check_link(None) is None
    with pytest.raises(ValueError):
        au.check_link("ftp://x")


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def world():
    acme, birch = uuid.uuid4(), uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for tid, n in ((acme, "acme"), (birch, "birch")):
            await conn.execute(
                text("insert into tenants (id, name, slug) values (:i, :n, :s)"), {"i": tid, "n": f"ta-{n}", "s": f"ta-{n}-{tid.hex[:8]}"}
            )
        await conn.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'SOC2')"), {"t": acme})
        await conn.execute(
            text(
                "insert into aisoc_compliance_evidence (id, tenant_id, framework, control_id, evidence_kind, summary, raw_payload, collected_at, status, created_at) "
                "values (:i, :t, 'SOC2', 'CC1.1', 'policy', 'x', '{}'::jsonb, now(), 'accepted', now())"
            ),
            {"i": uuid.uuid4(), "t": acme},
        )
        policy = uuid.uuid4()
        await conn.execute(
            text(
                "insert into governance_items (id, tenant_id, kind, title, owner, notes, interval_days, next_due, last_reviewed_at) values (:i, :t, 'policy', 'Acceptable use', 'Hal', '', 365, current_date, current_date)"
            ),
            {"i": policy, "t": acme},
        )
        other_policy = uuid.uuid4()
        await conn.execute(
            text(
                "insert into governance_items (id, tenant_id, kind, title, owner, notes, interval_days, next_due) values (:i, :t, 'policy', 'Birch policy', 'x', '', 365, current_date)"
            ),
            {"i": other_policy, "t": birch},
        )
    w = SimpleNamespace(
        acme=acme,
        birch=birch,
        policy=policy,
        other_policy=other_policy,
        engine=engine,
        user=SimpleNamespace(tenant_id=acme, user_id=None, email="hal@goliveoak.com"),
    )
    yield w
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        for t in (acme, birch):
            for table in (
                "audit_requests",
                "audits",
                "trust_center_settings",
                "governance_items",
                "aisoc_compliance_evidence",
                "compliance_enabled_frameworks",
            ):
                await conn.execute(text(f"delete from {table} where tenant_id = :t"), {"t": t})
        await conn.execute(text("delete from tenants where id = any(:t)"), {"t": [acme, birch]})
    await engine.dispose()


async def run(tenant, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tenant)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_the_trust_center_shows_health_as_it_is_now_only_the_chosen_policies_and_refuses_what_is_not_theirs(world):
    w = world
    empty = await run(w.acme, lambda db: tc.get_trust_center(w.acme, db, w.user))
    assert (
        not empty.enabled
        and empty.frameworks == []
        and empty.available_frameworks == ["SOC2"]
        and [p.title for p in empty.available_policies] == ["Acceptable use"]
    )
    body = tc.SettingsIn(
        enabled=True,
        headline="Security at Acme",
        about="We care.",
        contact_email="security@acme.com",
        frameworks=["SOC2", "HIPAA"],
        policy_ids=[w.policy],
        documents=[tc.DocumentIn(name="SOC 2 report", url="https://acme.example/soc2.pdf")],
    )
    out = await run(w.acme, lambda db: tc.put_trust_center(body, w.acme, db, w.user))
    assert out.enabled and out.headline == "Security at Acme" and out.updated_by == "hal@goliveoak.com"
    assert [f.framework for f in out.frameworks] == ["SOC2"], "HIPAA is not on, so it is not shown even though it was asked for"
    assert out.frameworks[0].healthy == 1 and out.frameworks[0].percent_healthy is not None and out.frameworks[0].controls > 40
    assert [p.title for p in out.policies] == ["Acceptable use"] and out.policies[0].last_reviewed_at is not None
    assert out.documents[0].url == "https://acme.example/soc2.pdf"
    with pytest.raises(HTTPException) as foreign:
        await run(w.acme, lambda db: tc.put_trust_center(tc.SettingsIn(policy_ids=[w.other_policy]), w.acme, db, w.user))
    assert foreign.value.status_code == 422
    with pytest.raises(HTTPException) as bad_link:
        await run(
            w.acme,
            lambda db: tc.put_trust_center(
                tc.SettingsIn(documents=[tc.DocumentIn(name="Oops", url="javascript:alert(1)")]), w.acme, db, w.user
            ),
        )
    assert bad_link.value.status_code == 422
    with pytest.raises(HTTPException) as bad_fw:
        await run(w.acme, lambda db: tc.put_trust_center(tc.SettingsIn(frameworks=["NOPE"]), w.acme, db, w.user))
    assert bad_fw.value.status_code == 422
    other = await run(w.birch, lambda db: tc.get_trust_center(w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None)))
    assert not other.enabled and other.headline == "" and other.policies == []


@needs_pg
@pytest.mark.asyncio
async def test_an_audit_gets_requests_for_the_controls_that_need_evidence_only_once_and_cannot_complete_while_any_is_open(world):
    w = world
    audit = await run(
        w.acme, lambda db: au.start_audit(au.AuditIn(name="SOC 2 Type II 2026", framework="SOC2", auditor="Prescient"), w.acme, db, w.user)
    )
    assert audit.status == "planning" and audit.requests == 0
    filled = await run(w.acme, lambda db: au.requests_from_controls(audit.id, w.acme, db, w.user))
    assert filled.requests > 40 and "CC1.1" not in {r.control_id for r in filled.items}, "CC1.1 is healthy, so it needs no request"
    again = await run(w.acme, lambda db: au.requests_from_controls(audit.id, w.acme, db, w.user))
    assert again.requests == filled.requests, "asking twice adds nothing new"
    first = filled.items[0]
    with pytest.raises(HTTPException) as nolink:
        await run(w.acme, lambda db: au.patch_request(audit.id, first.id, au.RequestPatch(link="javascript:x"), w.acme, db, w.user))
    assert nolink.value.status_code == 422
    provided = await run(
        w.acme,
        lambda db: au.patch_request(
            audit.id,
            first.id,
            au.RequestPatch(status="provided", note="Uploaded", link="https://x.example/f", owner="Hal"),
            w.acme,
            db,
            w.user,
        ),
    )
    assert provided.provided == 1 and provided.open == filled.requests - 1
    with pytest.raises(HTTPException) as open_left:
        await run(w.acme, lambda db: au.patch_audit(audit.id, au.AuditPatch(status="complete"), w.acme, db, w.user))
    assert open_left.value.status_code == 409 and "still open" in open_left.value.detail


@needs_pg
@pytest.mark.asyncio
async def test_a_small_audit_is_completed_locked_and_overdue_requests_are_counted_and_another_client_sees_none(world):
    w = world
    audit = await run(w.acme, lambda db: au.start_audit(au.AuditIn(name="ISO audit", framework="ISO27001"), w.acme, db, w.user))
    late = datetime.now(UTC).date() - timedelta(days=2)
    one = await run(
        w.acme, lambda db: au.add_request(audit.id, au.RequestIn(title="Org chart", owner="Dana", due_date=late), w.acme, db, w.user)
    )
    assert one.overdue == 1 and one.items[0].overdue
    done = await run(w.acme, lambda db: au.patch_request(audit.id, one.items[0].id, au.RequestPatch(status="accepted"), w.acme, db, w.user))
    assert done.accepted == 1 and done.overdue == 0
    final = await run(w.acme, lambda db: au.patch_audit(audit.id, au.AuditPatch(status="complete"), w.acme, db, w.user))
    assert final.status == "complete"
    with pytest.raises(HTTPException) as locked:
        await run(w.acme, lambda db: au.patch_request(audit.id, one.items[0].id, au.RequestPatch(note="late change"), w.acme, db, w.user))
    assert locked.value.status_code == 409
    with pytest.raises(HTTPException) as bad_period:
        await run(
            w.acme,
            lambda db: au.start_audit(
                au.AuditIn(name="Backwards", framework="SOC2", period_start=late, period_end=late - timedelta(days=5)), w.acme, db, w.user
            ),
        )
    assert bad_period.value.status_code == 422
    with pytest.raises(HTTPException) as bad_fw:
        await run(w.acme, lambda db: au.start_audit(au.AuditIn(name="Not a framework", framework="NOPE"), w.acme, db, w.user))
    assert bad_fw.value.status_code == 422
    other = await run(w.birch, lambda db: au.list_audits(w.birch, db, SimpleNamespace(tenant_id=w.birch, user_id=None)))
    assert other.audits == []
    with pytest.raises(HTTPException) as foreign:
        await run(w.birch, lambda db: au.get_audit(audit.id, w.birch, db, w.user))
    assert foreign.value.status_code == 404
