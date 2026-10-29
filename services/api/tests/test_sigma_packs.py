"""The imported Sigma rules as rule packs: loaded once at the parent, grouped into packs, applied to the clients the MSSP picks."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import mssp
from app.db.database import Base
from app.models.detection_rule import DetectionRule
from app.models.mssp import MSSPRulePack, MSSPRulePackAssignment, MSSPRulePackRule
from app.models.tenant import Tenant
from app.scripts.load_builtin_detections import detections_dir
from app.services import sigma_packs as sp
from app.services.sigma_imports import read_entries
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TABLES = [m.__table__ for m in (Tenant, DetectionRule, MSSPRulePack, MSSPRulePackRule, MSSPRulePackAssignment)]


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
    t = Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}".lower().replace(" ", "-"), parent_tenant_id=parent)
    s.add(t)
    await s.flush()
    return t


def entry(i, folder="endpoint", product="windows", category="process_creation", level="high", tags=("attack.t1003.001", "endpoint")):
    return {
        "id": f"sigmahq-sigma-{i}",
        "name": f"Rule {i}",
        "description": "d",
        "author": "SigmaHQ/sigma (licence DRL-1.1)",
        "tags": list(tags),
        "logsource_category": category,
        "logsource_product": product,
        "level": level,
        "sigma_yaml": f"id: sigmahq-sigma-{i}\nname: Rule {i}\n",
        "source_file": f"sigma-imports/{folder}/rule-{i}.yaml",
        "license_url": "https://example.test/licence",
    }


def test_each_rule_goes_in_the_pack_for_what_it_watches():
    assert sp.pack_key(entry(1)) == "windows"
    assert sp.pack_key(entry(2, product="linux")) == "linux"
    assert sp.pack_key(entry(3, folder="cloud", product="aws", category="")) == "cloud"
    assert sp.pack_key(entry(4, folder="network", product="", category="firewall")) == "network"
    assert sp.pack_key(entry(5, product="django", category="application")) == "applications"
    assert sp.pack_key(entry(6, product="", category="antivirus")) == "other"


def test_a_rule_row_carries_its_severity_techniques_and_where_it_came_from():
    v = sp.rule_values(entry(7, level="informational", tags=("attack.t1003.001", "attack.t1047", "cloud", "attack.initial-access")))
    assert v["severity"] == "info" and v["status"] == "active" and v["is_builtin"] is False
    assert v["mitre_techniques"] == ["T1003.001", "T1047"]
    assert v["category"] == "endpoint" and v["provenance"]["source_id"] == "sigmahq-sigma-7"
    assert sp.rule_values(entry(8, level="spicy"))["severity"] == "medium"


def test_loading_creates_rules_packs_and_memberships_once_and_never_overwrites_a_persons_edits():
    entries = [entry(1), entry(2), entry(3, product="linux")]

    async def body(s):
        parent = await tenant(s, "Parent")
        first = await sp.load_packs(s, parent.id, entries)
        await s.commit()
        edited = (await s.execute(select(DetectionRule).where(DetectionRule.name == "Rule 1"))).scalar_one()
        edited.status = "disabled"
        await s.commit()
        second = await sp.load_packs(s, parent.id, entries)
        await s.commit()
        rules = (await s.execute(select(DetectionRule))).scalars().all()
        packs = (await s.execute(select(MSSPRulePack))).scalars().all()
        links = (await s.execute(select(MSSPRulePackRule))).scalars().all()
        return first, second, rules, packs, links

    first, second, rules, packs, links = run(body)
    assert first == {"rules_created": 3, "rules_existing": 0, "packs_created": 2, "links_created": 3, "skipped": 0}
    assert second == {"rules_created": 0, "rules_existing": 3, "packs_created": 0, "links_created": 0, "skipped": 0}
    assert len(rules) == 3 and len(packs) == 2 and len(links) == 3
    assert {r.name: r.status for r in rules}["Rule 1"] == "disabled", "a status someone changed is left alone"
    assert {p.name for p in packs} == {"Sigma: Windows", "Sigma: Linux"}


def test_the_shipped_rules_make_the_six_packs_and_every_rule_lands_in_exactly_one():
    entries, _ = read_entries(detections_dir())

    async def body(s):
        parent = await tenant(s, "Parent")
        report = await sp.load_packs(s, parent.id, entries)
        await s.commit()
        return report

    report = run(body)
    assert report["rules_created"] == len(entries) >= 50
    assert report["links_created"] == len(entries), "one membership per rule"
    assert 2 <= report["packs_created"] <= len(sp.PACKS)


def test_the_overview_lists_each_pack_with_its_rules_and_the_clients_it_is_applied_to():
    async def body(s):
        parent = await tenant(s, "Parent")
        acme, beta = await tenant(s, "Acme", parent.id), await tenant(s, "Beta", parent.id)
        await sp.load_packs(s, parent.id, [entry(1), entry(2, product="linux")])
        await s.commit()
        windows = (await s.execute(select(MSSPRulePack).where(MSSPRulePack.name == "Sigma: Windows"))).scalar_one()
        who = SimpleNamespace(tenant_id=parent.id, id=uuid.uuid4())
        await mssp.set_pack_for_client(windows.id, acme.id, mssp.PackClientRequest(enabled=True), db=s, current_user=who)
        overview = await mssp.rule_packs_overview(db=s, current_user=who)
        return overview, acme.id, beta.id

    overview, acme_id, beta_id = run(body)
    by_name = {p.name: p for p in overview}
    assert [r.name for r in by_name["Sigma: Windows"].rules] == ["Rule 1"]
    assert by_name["Sigma: Windows"].applied_to == [acme_id]
    assert by_name["Sigma: Linux"].applied_to == [] and beta_id not in by_name["Sigma: Windows"].applied_to


def test_ticking_and_unticking_a_client_is_a_state_not_a_pile_of_rows():
    async def body(s):
        parent = await tenant(s, "Parent")
        acme = await tenant(s, "Acme", parent.id)
        await sp.load_packs(s, parent.id, [entry(1)])
        await s.commit()
        pack = (await s.execute(select(MSSPRulePack))).scalar_one()
        who = SimpleNamespace(tenant_id=parent.id, id=uuid.uuid4())

        async def put(enabled):
            await mssp.set_pack_for_client(pack.id, acme.id, mssp.PackClientRequest(enabled=enabled), db=s, current_user=who)
            rows = (await s.execute(select(MSSPRulePackAssignment))).scalars().all()
            return [(r.enabled) for r in rows]

        return [await put(True), await put(True), await put(False), await put(True)]

    assert run(body) == [[True], [True], [False], [True]]


def test_a_pack_or_client_that_is_not_yours_is_a_404_and_nothing_is_written():
    async def body(s):
        parent, other_parent = await tenant(s, "Parent"), await tenant(s, "Other parent")
        mine, theirs = await tenant(s, "Mine", parent.id), await tenant(s, "Theirs", other_parent.id)
        await sp.load_packs(s, parent.id, [entry(1)])
        await sp.load_packs(s, other_parent.id, [entry(1)])
        await s.commit()
        my_pack = (await s.execute(select(MSSPRulePack).where(MSSPRulePack.parent_tenant_id == parent.id))).scalar_one()
        their_pack = (await s.execute(select(MSSPRulePack).where(MSSPRulePack.parent_tenant_id == other_parent.id))).scalar_one()
        who = SimpleNamespace(tenant_id=parent.id, id=uuid.uuid4())
        errors = []
        for pack, child in ((their_pack, mine), (my_pack, theirs), (my_pack, uuid.uuid4() and parent)):
            with pytest.raises(HTTPException) as e:
                await mssp.set_pack_for_client(pack.id, child.id, mssp.PackClientRequest(enabled=True), db=s, current_user=who)
            errors.append(e.value.status_code)
        rows = (await s.execute(select(MSSPRulePackAssignment))).scalars().all()
        return errors, rows

    errors, rows = run(body)
    assert errors == [404, 404, 404] and rows == []


def test_the_seeded_counts_say_how_many_built_in_rules_and_how_many_are_in_each_pack():
    from app.api.v1.endpoints.detection_rules import seeded_counts

    async def body(s):
        parent, other = await tenant(s, "Parent"), await tenant(s, "Other parent")
        s.add(
            DetectionRule(
                id=uuid.uuid4(),
                tenant_id=None,
                name="Built in",
                description="d",
                rule_language="sigma",
                rule_body="x",
                category="endpoint",
                status="active",
                severity="low",
                confidence=50,
                is_builtin=True,
            )
        )
        s.add(
            DetectionRule(
                id=uuid.uuid4(),
                tenant_id=parent.id,
                name="Own rule",
                description="d",
                rule_language="sigma",
                rule_body="x",
                category="endpoint",
                status="active",
                severity="low",
                confidence=50,
                is_builtin=False,
            )
        )
        await sp.load_packs(s, parent.id, [entry(1), entry(2), entry(3, product="linux")])
        await sp.load_packs(s, other.id, [entry(9)])
        await s.commit()
        who = SimpleNamespace(tenant_id=parent.id, id=uuid.uuid4())
        return await seeded_counts(current_user=who, db=s)

    got = run(body)
    assert got.builtin == 1, "a tenant's own rule is not a built-in one"
    assert got.imported == 3, "another organization's packs are not counted"
    assert [(p.name, p.rules) for p in got.packs] == [("Sigma: Linux", 1), ("Sigma: Windows", 2)]


def test_one_malformed_entry_is_skipped_and_counted_and_the_rest_still_load():
    good = [entry(1), entry(2, product="linux")]
    broken = [
        {"name": "No id"},
        {"id": "x", "sigma_yaml": "title: x"},
        "not even a dict",
        {**entry(9), "sigma_yaml": None} | {"name": None},
    ]

    async def body(s):
        parent = await tenant(s, "Parent")
        report = await sp.load_packs(s, parent.id, [good[0], *broken, good[1]])
        await s.commit()
        rules = (await s.execute(select(DetectionRule))).scalars().all()
        links = (await s.execute(select(MSSPRulePackRule))).scalars().all()
        return report, rules, links

    report, rules, links = run(body)
    assert report["skipped"] >= 3 and report["rules_created"] >= 2, report
    assert {"Rule 1", "Rule 2"} <= {r.name for r in rules}
    assert len(links) == report["links_created"] == report["rules_created"], "every rule that loaded is in a pack"


def test_memberships_are_read_in_one_query_and_flushed_once_however_many_rules():
    from sqlalchemy import event

    entries = [entry(i, product="windows" if i % 2 else "linux") for i in range(1, 41)]
    statements: list[str] = []

    async def body(s):
        parent = await tenant(s, "Parent")
        engine = s.bind
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cur, stmt, params, ctx, many: statements.append(stmt))
        statements.clear()
        first = await sp.load_packs(s, parent.id, entries)
        await s.commit()
        loaded = len(statements)
        statements.clear()
        second = await sp.load_packs(s, parent.id, entries)
        await s.commit()
        return first, second, loaded, len(statements)

    first, second, with_inserts, rerun = run(body)
    assert first["rules_created"] == 40 and second["rules_created"] == 0
    assert rerun <= 6, f"a reload of 40 existing rules took {rerun} statements: it used to be one flush and one lookup per rule"
    assert with_inserts < 40 * 2, f"{with_inserts} statements to load 40 rules"
