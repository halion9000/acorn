"""Policy templates: the fields fill themselves in, a gap stays visible, and a policy made from a template keeps its fields so they always show today's facts.

The pure rules first, then the endpoints against a REAL Postgres (AISOC_TEST_PG_URL, a disposable fully migrated database).
"""

import os
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import governance as ep
from app.services import policy_templates as pt
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

DAY = date(2026, 11, 14)


def values(**over):
    return pt.field_values(
        **{
            "client_name": "Live Oak IT Partners",
            "owner": "Hal",
            "version": 3,
            "last_updated": date(2026, 10, 1),
            "review_date": date(2027, 10, 1),
            "today": DAY,
            **over,
        }
    )


def test_every_field_is_filled_and_an_empty_one_or_an_unknown_name_stays_visible():
    text_ = "{{client_name}} v{{version}} by {{ owner }} on {{date}} / {{last_updated}} / {{review_date}} / {{nonsense}}"
    assert pt.render(text_, values()) == "Live Oak IT Partners v3 by Hal on 2026-11-14 / 2026-10-01 / 2027-10-01 / {{nonsense}}"
    assert pt.render("by {{owner}}", values(owner="")) == "by {{owner}}", "no owner yet: the gap shows, it is not silently blank"


def test_the_templates_are_complete_distinct_and_use_only_known_fields():
    assert (
        len(pt.TEMPLATES) >= 6
        and len({t.key for t in pt.TEMPLATES}) == len(pt.TEMPLATES)
        and len({t.title for t in pt.TEMPLATES}) == len(pt.TEMPLATES)
    )
    for t in pt.TEMPLATES:
        assert t.body.startswith(f"# {t.title}") and len(t.body) > 800, t.key
        assert set(pt.fields_used(t.body)) <= set(pt.FIELDS), t.key
        assert {"client_name", "version", "review_date"} <= set(pt.fields_used(t.body)), t.key
        assert "{{" not in pt.render(t.body, values()), f"{t.key} still has an unfilled field with every value given"


def test_fields_used_lists_each_once_in_order():
    assert pt.fields_used("{{owner}} {{date}} {{owner}}") == ["owner", "date"]


PG_URL = os.environ.get("AISOC_TEST_PG_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="set AISOC_TEST_PG_URL to a DISPOSABLE, fully migrated API database")


async def off(s):
    await s.execute(text("select set_config('app.rls_fail_closed', 'off', true)"))


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    async def noop(**_kw):
        return None

    monkeypatch.setattr(ep, "emit_audit", noop)


@pytest.fixture
async def world():
    engine = create_async_engine(PG_URL, poolclass=NullPool)
    a = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        await off(s)
        await s.execute(text("insert into tenants (id, name, slug) values (:t, 'Acme Dental', :s)"), {"t": a, "s": f"pt-{a.hex[:10]}"})
        await s.commit()
        s.info.update(a=a)
        yield s
        await off(s)
        await s.execute(text("delete from governance_versions where tenant_id = :a"), {"a": a})
        await s.execute(text("delete from governance_items where tenant_id = :a"), {"a": a})
        await s.execute(text("delete from tenants where id = :a"), {"a": a})
        await s.commit()
    await engine.dispose()


def user(t):
    return SimpleNamespace(tenant_id=t, user_id=None)


@needs_pg
@pytest.mark.asyncio
async def test_a_policy_from_a_template_keeps_its_fields_and_shows_them_filled_with_the_current_facts(world):
    s, a = world, world.info["a"]
    await off(s)
    listed = await ep.list_templates(user(a), s)
    assert all(not t.added for t in listed) and "Acme Dental" in listed[0].summary
    await off(s)
    made = await ep.create_from_template(ep.FromTemplate(key="access-control", owner="Dana"), None, user(a), s)
    assert made.kind == "policy" and made.versions == 1 and made.owner == "Dana"
    await off(s)
    stored = await ep.list_versions(made.id, user(a), s)
    assert "{{client_name}}" in stored[0].body, "the stored text keeps the fields"
    await off(s)
    out = await ep.rendered_version(made.id, user(a), s)
    assert "Organization: Acme Dental" in out.text and "Policy owner: Dana" in out.text and "{{" not in out.text and out.missing == []
    await off(s)
    assert [t.added for t in await ep.list_templates(user(a), s) if t.key == "access-control"] == [True]
    with pytest.raises(HTTPException) as dup:
        await off(s)
        await ep.create_from_template(ep.FromTemplate(key="access-control"), None, user(a), s)
    assert dup.value.status_code == 409
    with pytest.raises(HTTPException) as nope:
        await off(s)
        await ep.create_from_template(ep.FromTemplate(key="nope"), None, user(a), s)
    assert nope.value.status_code == 404


@needs_pg
@pytest.mark.asyncio
async def test_a_policy_with_no_owner_names_the_gap_and_an_unknown_version_is_refused(world):
    s, a = world, world.info["a"]
    await off(s)
    made = await ep.create_from_template(ep.FromTemplate(key="incident-response"), None, user(a), s)
    await off(s)
    out = await ep.rendered_version(made.id, user(a), s)
    assert "owner" in out.missing and "{{owner}}" in out.text
    with pytest.raises(HTTPException) as e:
        await off(s)
        await ep.rendered_version(made.id, user(a), s, version=9)
    assert e.value.status_code == 404
    _ = datetime.now(UTC)
