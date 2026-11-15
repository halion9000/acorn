"""Our own control health from Secureframe: each requirement's verdict becomes evidence for that control, a person's own evidence is never touched.

The pure mapping first, then the sync and the dashboard against a REAL Postgres (AISOC_TEST_PG_URL / AISOC_TEST_PG_APP_URL, a disposable fully migrated database).
"""

import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import compliance_dashboard as dash
from app.db.rls import set_rls_context
from app.services import secureframe_evidence as se
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

NOW = datetime(2026, 11, 14, tzinfo=UTC)


def req(framework, key, health, passing=3, failing=0):
    return {
        "framework": framework,
        "key": key,
        "title": f"Title {key}",
        "health": health,
        "controls": [{"key": "c", "passing": passing, "failing": failing}],
    }


def test_healthy_becomes_accepted_unhealthy_rejected_and_untested_or_unknown_nothing():
    rows = se.evidence_rows(
        [
            req("NIST_CSF_2", "GV.OC-01", "healthy", 4, 0),
            req("NIST_CSF_2", "GV.OC-02", "unhealthy", 1, 2),
            req("NIST_CSF_2", "GV.OC-03", "not_tested"),
            req("NIST_CSF_2", "GV.OC-04", "not_applicable"),
            req("NIST_CSF_2", "NOT-A-CONTROL", "healthy"),
            req("SOC2_UNKNOWN", "CC1.1", "healthy"),
            req("CIS_IG1", "1.1", "healthy"),
        ]
    )
    assert [(r["framework"], r["control_id"], r["status"]) for r in rows] == [
        ("NIST-CSF", "GV.OC-01", "accepted"),
        ("NIST-CSF", "GV.OC-02", "rejected"),
        ("CIS-IG1", "1.1", "accepted"),
    ]
    assert rows[1]["payload"] == {"source": "secureframe", "health": "unhealthy", "passing": 1, "failing": 2}
    assert "1 test passing, 2 failing" in rows[1]["summary"]


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
APP_URL = os.environ.get("AISOC_TEST_PG_APP_URL", "")
needs_pg = pytest.mark.skipif(
    not (PG_URL and APP_URL), reason="set AISOC_TEST_PG_URL and AISOC_TEST_PG_APP_URL to a DISPOSABLE, fully migrated API database"
)


@pytest.fixture
async def tenant():
    tid = uuid.uuid4()
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(
            text("insert into tenants (id, name, slug) values (:i, 'sf-evidence', :s)"), {"i": tid, "s": f"sfe-{tid.hex[:8]}"}
        )
    yield tid
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("delete from aisoc_compliance_evidence where tenant_id = :t"), {"t": tid})
        await conn.execute(text("delete from compliance_enabled_frameworks where tenant_id = :t"), {"t": tid})
        await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
    await engine.dispose()


async def with_db(tid, work):
    engine = create_async_engine(APP_URL, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await set_rls_context(db, tid)
            return await work(db)
    finally:
        await engine.dispose()


@needs_pg
@pytest.mark.asyncio
async def test_a_sync_replaces_only_its_own_records_and_a_persons_rejection_still_wins(tenant):
    async def work(db):
        await db.execute(
            text(
                "insert into aisoc_compliance_evidence (tenant_id, framework, control_id, evidence_kind, summary, status, collected_at) "
                "values (:t, 'NIST-CSF', 'GV.OC-01', 'attestation', 'a person rejected this', 'rejected', :n), "
                "(:t, 'NIST-CSF', 'GV.OC-05', 'attestation', 'a person accepted this', 'accepted', :n)"
            ),
            {"t": tenant, "n": NOW},
        )
        first = await se.sync(db, tenant, [req("NIST_CSF_2", "GV.OC-01", "healthy"), req("NIST_CSF_2", "GV.OC-02", "unhealthy")], NOW)
        again = await se.sync(db, tenant, [req("NIST_CSF_2", "GV.OC-02", "healthy")], NOW)
        await db.commit()
        rows = (
            await db.execute(
                text(
                    "select control_id, status, raw_payload ->> 'source' as src from aisoc_compliance_evidence where tenant_id = :t order by control_id, status"
                ),
                {"t": tenant},
            )
        ).all()
        return first, again, rows

    first, again, rows = await with_db(tenant, work)
    assert first == {"written": 2} and again == {"written": 1}
    assert [(r.control_id, r.status, r.src) for r in rows] == [
        (
            "GV.OC-01",
            "rejected",
            None,
        ),  # the person's own, kept; the Secureframe one for it was replaced and the new report does not mention it
        ("GV.OC-02", "accepted", "secureframe"),
        ("GV.OC-05", "accepted", None),
    ]


@needs_pg
@pytest.mark.asyncio
async def test_the_dashboard_counts_the_secureframe_verdicts_as_control_health(tenant):
    async def work(db):
        await db.execute(text("insert into compliance_enabled_frameworks (tenant_id, framework) values (:t, 'NIST-CSF')"), {"t": tenant})
        await se.sync(
            db,
            tenant,
            [
                req("NIST_CSF_2", "GV.OC-01", "healthy"),
                req("NIST_CSF_2", "GV.OC-02", "healthy"),
                req("NIST_CSF_2", "GV.OC-03", "unhealthy"),
            ],
            NOW,
        )
        await db.commit()
        user = SimpleNamespace(tenant_id=tenant, user_id=None)
        return await dash.dashboard(tenant, db, user)

    out = await with_db(tenant, work)
    assert out.health is not None and out.health.healthy == 2 and out.health.unhealthy == 1
    assert out.health.total > 3 and out.health.not_tested == out.health.total - 3
