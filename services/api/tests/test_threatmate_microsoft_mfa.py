"""Microsoft 365 people read by ThreatMate for a client without CIPP: judged on enrolment, and replaced by CIPP's when it reports."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import identity as ident
from app.services.mfa_registration import directory_of, microsoft_rows
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


def person(source="threatmate-microsoft", registered=False, admin=False, enabled=True, ca=False):
    return SimpleNamespace(
        source=source,
        enabled=enabled,
        licensed=True,
        user_type="Member",
        registered=registered,
        capable=registered,
        methods=[],
        per_user=None,
        ca_enforced=ca,
        security_defaults=False,
        admin=admin,
    )


def test_an_enrolled_person_counts_as_covered_and_an_unenrolled_one_as_none_with_no_requirement_to_report():
    counts = ident.counts_for_mfa(
        [person(registered=True), person(registered=True), person(registered=False, admin=True), person(enabled=False)]
    )
    assert counts == {"people": 3, "with_mfa": 2, "not_required": 0, "without_mfa": 1, "admins_without_mfa": 1, "registration_unknown": 0}


def test_these_rows_are_microsoft_people_not_google_and_are_judged_apart_from_ciPPs_fallback():
    row = person()
    assert directory_of(row) == "Microsoft 365" and microsoft_rows([row]) == [row]
    # With CIPP rows that report no registration at all, CIPP's own people still use the fallback; ThreatMate's are not dragged into it.
    cipp_unknown = person(source="cipp", registered=False, ca=True)
    counts = ident.counts_for_mfa([cipp_unknown, person(registered=True)])
    assert counts["registration_unknown"] == 1 and counts["with_mfa"] == 2


def test_only_the_threatmate_microsoft_source_may_be_named_as_the_storage_source():
    base = {"vendor": "threatmate", "vendor_client_id": "1", "snapshot_id": str(uuid.uuid4()), "items": []}
    assert ident.MfaUsersReport.model_validate({**base, "source": "threatmate-microsoft"}).source == "threatmate-microsoft"
    assert ident.MfaUsersReport.model_validate(base).source is None
    with pytest.raises(ValueError):
        ident.MfaUsersReport.model_validate({**base, "source": "cipp"})


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def item(n, registered=True):
    return {"id": f"m-{n}", "upn": f"u{n}@acme.com", "licensed": True, "registered": registered, "capable": registered}


@pg
@pytest.mark.asyncio
async def test_cipp_replaces_threatmates_copy_and_threatmates_copy_is_not_kept_while_cipp_reports(monkeypatch):
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    tid = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("set local session_replication_role = replica"))
        await conn.execute(text("insert into tenants (id, name, slug) values (:t, 'tmms', :s)"), {"t": tid, "s": f"tm-{tid.hex[:10]}"})

    async def targets(_db, _owner, _view):
        return {tid: None}, 0, 0, []

    monkeypatch.setattr(ident, "targets_by_tenant", targets)

    def report(vendor, source, *items):
        return ident.MfaUsersReport.model_validate(
            {
                "vendor": vendor,
                "source": source,
                "vendor_client_id": "x",
                "snapshot_id": str(uuid.uuid4()),
                "last": True,
                "items": list(items),
            }
        )

    async def stored(db):
        rows = (
            await db.execute(
                text("select source, count(*) from identity_mfa_users where tenant_id = :t group by source order by source"), {"t": tid}
            )
        ).all()
        return {r[0]: r[1] for r in rows}

    try:
        async with AsyncSession(engine) as db:
            await ident.apply_mfa_users(db, uuid.uuid4(), report("threatmate", "threatmate-microsoft", item(1), item(2, False)))
            await db.commit()
            assert await stored(db) == {"threatmate-microsoft": 2}
            # CIPP arrives for the client: its people are kept and ThreatMate's copy of the Microsoft people goes.
            await ident.apply_mfa_users(db, uuid.uuid4(), report("cipp", None, item(3)))
            await db.commit()
            assert await stored(db) == {"cipp": 1}
            # ThreatMate reports again: with CIPP present nothing of it is stored.
            out = await ident.apply_mfa_users(db, uuid.uuid4(), report("threatmate", "threatmate-microsoft", item(1)))
            await db.commit()
            assert out.accepted == 0 and await stored(db) == {"cipp": 1}
            # A Google report (the vendor's own source) is not touched by any of this.
            await ident.apply_mfa_users(db, uuid.uuid4(), report("threatmate", None, item(9)))
            await db.commit()
            assert await stored(db) == {"cipp": 1, "threatmate": 1}
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("set local session_replication_role = replica"))
            await conn.execute(text("delete from identity_mfa_users where tenant_id = :t"), {"t": tid})
            await conn.execute(text("delete from tenants where id = :t"), {"t": tid})
        await engine.dispose()
