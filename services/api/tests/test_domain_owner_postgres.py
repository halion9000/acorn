"""ThreatMate alerts filed under the MSP move to the client whose people use the alert's domain, against a REAL Postgres.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database; the owner role, as moving an alert's tenant needs).
"""

import json
import os
import uuid

import pytest
from app.services.alert_reroute import reroute_alerts
from app.services.domain_owner import domain_owners
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def tm(device, source="threatmate"):
    return json.dumps({"source": source, "unmapped": {"context": {"device_name": device, "threatmate_client_id": "11085"}}})


@pytest.fixture
async def world():
    tag = uuid.uuid4().hex[:10]
    ids = {k: uuid.uuid4() for k in ("parent", "acme", "birch", "other_parent", "other_child", "msp_child")}
    a: dict[str, uuid.UUID] = {}
    owner = create_async_engine(PG_URL)
    snap = uuid.uuid4()
    try:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for key, tid in ids.items():
                parent = ids["parent"] if key in ("acme", "birch", "msp_child") else ids["other_parent"] if key == "other_child" else None
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{key}-{tag}", "s": f"{key}-{tag}", "p": parent, "r": "child" if parent else "parent"},
                )

            async def people(tenant, domain, n, user_type="Member", enabled=True):
                for i in range(n):
                    await conn.execute(
                        text(
                            "insert into identity_mfa_users (tenant_id, source, user_id, upn, enabled, user_type, admin, licensed, registered, capable, ca_enforced, security_defaults, snapshot_id) "
                            "values (:t, 'cipp', :u, :upn, :en, :ut, false, true, true, true, false, false, :s)"
                        ),
                        {"t": ids[tenant], "u": f"{tenant}-{domain}-{i}-{tag}", "upn": f"user{i}@{domain}", "en": enabled, "ut": user_type, "s": snap},
                    )

            await people("acme", "acme-clinic.org", 5)  # the client's own domain
            await people("acme", "shared-mail.com", 3)  # a domain two clients both use: ambiguous
            await people("birch", "shared-mail.com", 4)
            await people("birch", "birch-co.com", 1)  # one address is not enough to own a domain
            await people("birch", "guests-only.org", 4, user_type="Guest")
            await people("birch", "disabled.org", 4, enabled=False)
            await people("other_child", "acme-clinic.org", 5)  # another MSP's client: must not count
            rows = [
                ("host", "parent", tm("webdisk.acme-clinic.org"), "d1"),
                ("mail_address", "parent", tm("Pat@ACME-clinic.org"), "d2"),
                ("ambiguous", "parent", tm("mail.shared-mail.com"), "d3"),
                ("lone_user", "parent", tm("www.birch-co.com"), "d4"),
                ("guests", "parent", tm("www.guests-only.org"), "d5"),
                ("disabled", "parent", tm("www.disabled.org"), "d6"),
                ("own_domain", "parent", tm("www.msp-own.com"), "d7"),
                ("not_a_host", "parent", tm("NUC-CFGC-KAUF"), "d8"),
                ("other_vendor", "parent", tm("webdisk.acme-clinic.org", source="huntress"), "d9"),
                ("dup_parent", "parent", tm("ftp.acme-clinic.org"), "dup"),
                ("dup_child", "acme", tm("ftp.acme-clinic.org"), "dup"),
                ("other_parents", "other_parent", tm("webdisk.acme-clinic.org"), "d10"),
                # ThreatMate's MSP segments are mapped to a CLIENT tenant of the MSP, so the alerts sit there, not under the MSP itself
                ("seg_host", "msp_child", tm("vpn.acme-clinic.org"), "e1"),
                ("seg_own_domain", "msp_child", tm("www.msp-own.com"), "e2"),
                ("seg_ip", "msp_child", tm("203.0.113.9"), "e3"),
            ]
            for name, owner_key, rawj, h in rows:
                a[name] = uuid.uuid4()
                await conn.execute(
                    text(
                        "insert into alerts (id, tenant_id, title, severity, status, raw_event, dedup_hash, created_at, event_time, first_seen, last_seen) "
                        "values (:id, :t, :n, 'high', 'new', cast(:raw as jsonb), :h, now(), now(), now(), now())"
                    ),
                    {"id": a[name], "t": ids[owner_key], "n": name, "raw": rawj, "h": h},
                )
        yield ids, a, owner
    finally:
        async with owner.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            tids = [str(x) for x in ids.values()]
            await conn.execute(text("delete from alerts where tenant_id = any(cast(:t as uuid[]))"), {"t": tids})
            await conn.execute(text("delete from identity_mfa_users where tenant_id = any(cast(:t as uuid[]))"), {"t": tids})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"), {"t": tids})
            await conn.execute(text("delete from tenants where id = any(cast(:t as uuid[]))"), {"t": tids})
        await owner.dispose()


async def where(owner, alert_id):
    async with owner.begin() as conn:
        await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
        return (await conn.execute(text("select tenant_id from alerts where id = :i"), {"i": alert_id})).scalar_one()


async def test_a_domain_belongs_to_the_one_client_of_this_msp_with_enough_people_on_it(world):
    ids, _a, owner = world
    async with async_sessionmaker(owner, expire_on_commit=False)() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        owners = await domain_owners(s, ids["parent"])
    assert owners == {"acme-clinic.org": ids["acme"]}, "ambiguous, lone-user, guest, disabled and other-MSP domains belong to nobody"


async def test_threatmate_alerts_filed_under_the_msp_move_to_the_client_that_owns_their_domain_and_nothing_else_moves(world):
    ids, a, owner = world
    async with async_sessionmaker(owner, expire_on_commit=False)() as s:
        await s.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
        result = await reroute_alerts(s, ids["parent"])
        await s.commit()
    assert result.moved == 3 and result.left_duplicates == 1
    assert {k.split("-")[0]: v for k, v in result.by_client.items()} == {"acme": 3}
    moved = {n: await where(owner, a[n]) for n in a}
    assert moved["host"] == moved["mail_address"] == moved["seg_host"] == ids["acme"], "including the one filed under the client tenant the MSP's own segments map to"
    for stays in ("ambiguous", "lone_user", "guests", "disabled", "own_domain", "not_a_host", "other_vendor", "dup_parent"):
        assert moved[stays] == ids["parent"], stays
    assert moved["seg_own_domain"] == moved["seg_ip"] == ids["msp_child"], "the MSP's own domain and a bare address belong to nobody, so they stay"
    assert moved["dup_child"] == ids["acme"] and moved["other_parents"] == ids["other_parent"]
