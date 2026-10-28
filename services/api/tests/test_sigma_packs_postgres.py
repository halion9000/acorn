"""Rule packs end to end against a REAL Postgres: a pack applied to one client reaches that client's effective rules, and no other client's.

Opt in with AISOC_TEST_PG_URL (a DISPOSABLE, fully migrated database).
"""

import os
import uuid

import pytest
from app.services import sigma_packs as sp
from app.services.mssp_rule_resolver import resolve_effective_rules
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


def entry(i, product="windows", category="process_creation"):
    return {
        "id": f"sigmahq-sigma-pgtest-{i}-{uuid.uuid4().hex[:6]}",
        "name": f"Pack test rule {i}",
        "description": "d",
        "author": "SigmaHQ/sigma",
        "tags": ["attack.t1003.001"],
        "logsource_category": category,
        "logsource_product": product,
        "level": "high",
        "sigma_yaml": f"title: Pack test rule {i}\n",
        "source_file": f"sigma-imports/endpoint/pack-test-{i}.yaml",
        "license_url": "",
    }


@pytest.fixture
async def world():
    parent, acme, beta = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:8]
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            for tid, name, p, role in (
                (parent, "parent", None, "parent"),
                (acme, "acme", parent, "child"),
                (beta, "beta", parent, "child"),
            ):
                await conn.execute(
                    text("insert into tenants (id, name, slug, parent_tenant_id, mssp_role) values (:i, :n, :s, :p, :r)"),
                    {"i": tid, "n": f"{name}-{tag}", "s": f"{name}-{tag}", "p": p, "r": role},
                )
        yield engine, parent, acme, beta
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            ids = [parent, acme, beta]
            await conn.execute(
                text("delete from mssp_rule_pack_assignments where child_tenant_id = any(cast(:t as uuid[]))"), {"t": [str(i) for i in ids]}
            )
            await conn.execute(text("delete from mssp_rule_packs where parent_tenant_id = :p"), {"p": parent})
            await conn.execute(text("delete from detection_rules where tenant_id = any(cast(:t as uuid[]))"), {"t": [str(i) for i in ids]})
            await conn.execute(
                text("delete from tenants where id = any(cast(:t as uuid[])) and parent_tenant_id is not null"),
                {"t": [str(i) for i in ids]},
            )
            await conn.execute(text("delete from tenants where id = :p"), {"p": parent})
        await engine.dispose()


async def session(engine):
    db = async_sessionmaker(engine, expire_on_commit=False)()
    await db.execute(text("select set_config('app.rls_fail_closed', 'off', false)"))
    return db


@pytest.mark.asyncio
async def test_a_pack_applied_to_one_client_gives_that_client_its_rules_and_nobody_else(world):
    engine, parent, acme, beta = world
    entries = [entry(1), entry(2), entry(3, product="linux", category="process_creation")]
    db = await session(engine)
    report = await sp.load_packs(db, parent, entries)
    await db.commit()
    assert report["rules_created"] == 3 and report["packs_created"] == 2

    before = await resolve_effective_rules(db, acme)
    assert [r for r in before if r.source == "pack"] == [], "nothing is applied until the MSSP applies a pack"

    pack_id = (
        await db.execute(text("select id from mssp_rule_packs where parent_tenant_id = :p and name = 'Sigma: Windows'"), {"p": parent})
    ).scalar_one()
    await db.execute(
        text("insert into mssp_rule_pack_assignments (pack_id, child_tenant_id, enabled) values (:p, :c, true)"), {"p": pack_id, "c": acme}
    )
    await db.commit()

    acme_rules = [r for r in await resolve_effective_rules(db, acme) if r.source == "pack"]
    beta_rules = [r for r in await resolve_effective_rules(db, beta) if r.source == "pack"]
    await db.close()
    assert sorted(r.name for r in acme_rules) == ["Pack test rule 1", "Pack test rule 2"], "the Windows pack's rules, not the Linux pack's"
    assert beta_rules == [], "a client the pack was not applied to gets nothing"


@pytest.mark.asyncio
async def test_the_startup_seeding_loads_the_packs_for_the_parent_and_a_second_start_adds_nothing(world):
    from app.services.seed_shipped_detections import seed_packs

    engine, parent, acme, _beta = world
    entries = [entry(10), entry(11)]
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def mine():
        async with engine.begin() as conn:
            await conn.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))
            rules = (await conn.execute(text("select count(*) from detection_rules where tenant_id = :p"), {"p": parent})).scalar_one()
            for_child = (await conn.execute(text("select count(*) from detection_rules where tenant_id = :c"), {"c": acme})).scalar_one()
        return rules, for_child

    first = await seed_packs(factory, entries)
    assert first["rules_created"] >= 2 and first["parents"] >= 1
    assert await mine() == (2, 0), "the rules are the parent's own; none is copied into a client"
    await seed_packs(factory, entries)
    assert await mine() == (2, 0), "a second start adds nothing"
