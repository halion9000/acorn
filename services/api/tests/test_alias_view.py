"""The owner's client mapping is read once and shared briefly, and a change to it is never hidden behind that."""

import uuid
from types import SimpleNamespace as NS

import pytest
from app.models.client_alias import ClientAlias
from app.models.tenant import Tenant
from app.services import alias_view as av


class Db:
    """Answers the two reads the view makes (the aliases, then the child tenants) and counts them."""

    def __init__(self, aliases, children):
        self.aliases, self.children, self.reads = aliases, children, 0

    async def execute(self, _stmt):
        self.reads += 1
        data = self.aliases if self.reads % 2 == 1 else self.children
        return NS(scalars=lambda: NS(all=lambda: data))


def alias(vendor, vid, child=None, ignored=False, name=None):
    return NS(vendor=vendor, vendor_client_id=vid, child_tenant_id=child, ignored=ignored, vendor_client_name=name)


@pytest.fixture(autouse=True)
def clean():
    av.forget_aliases()
    yield
    av.forget_aliases()


async def test_the_mapping_is_read_once_and_then_served_from_memory():
    owner, child = uuid.uuid4(), uuid.uuid4()
    db = Db([alias("huntress", "7", child, name="Acme"), alias("petra", "p1", None, ignored=True)], [child])
    known, children = await av.alias_view(db, owner)
    assert known[("huntress", "7")] == av.AliasView(False, child, "Acme") and known[("petra", "p1")].ignored is True
    assert children == frozenset({child})
    again = await av.alias_view(db, owner)
    assert again[0] is known and db.reads == 2, "the second ask made no query"


async def test_each_owner_has_its_own_mapping():
    a, b = uuid.uuid4(), uuid.uuid4()
    db_a, db_b = Db([alias("huntress", "1")], []), Db([alias("huntress", "2")], [])
    ka, _ = await av.alias_view(db_a, a)
    kb, _ = await av.alias_view(db_b, b)
    assert list(ka) == [("huntress", "1")] and list(kb) == [("huntress", "2")]


async def test_it_is_read_again_when_forgotten_and_when_it_has_expired(monkeypatch):
    owner = uuid.uuid4()
    db = Db([alias("huntress", "7")], [])
    await av.alias_view(db, owner)
    av.forget_aliases()
    await av.alias_view(db, owner)
    assert db.reads == 4, "forgotten: read again"
    monkeypatch.setattr(av, "TTL_SECONDS", 0.0)
    await av.alias_view(db, owner)
    assert db.reads == 6, "expired: read again"


async def test_writing_an_alias_or_a_tenant_through_the_orm_clears_it_and_anything_else_does_not():
    owner = uuid.uuid4()
    db = Db([alias("huntress", "7")], [])
    await av.alias_view(db, owner)
    session = NS(new=[object()], dirty=[], deleted=[])
    av._forget_on_flush(session, None, None)
    assert await av.alias_view(db, owner) and db.reads == 2, "an unrelated object changed: still kept"
    for changed in (
        ClientAlias(tenant_id=owner, vendor="x", vendor_client_id="1", vendor_client_name="n", normalized_name="n"),
        Tenant(name="t", slug="t"),
    ):
        await av.alias_view(db, owner)
        av._forget_on_flush(NS(new=[changed], dirty=[], deleted=[]), None, None)
        before = db.reads
        await av.alias_view(db, owner)
        assert db.reads == before + 2, type(changed).__name__
    await av.alias_view(db, owner)
    av._forget_on_flush(NS(new=[], dirty=[changed], deleted=[]), None, None)
    before = db.reads
    await av.alias_view(db, owner)
    assert db.reads == before + 2, "a change to an existing one clears it too"


async def test_a_bulk_alias_update_or_insert_clears_it_but_a_read_or_another_table_does_not():
    owner = uuid.uuid4()
    db = Db([alias("huntress", "7")], [])
    await av.alias_view(db, owner)
    mapper = NS(class_=ClientAlias)
    other = NS(class_=dict)
    av._forget_on_dml(NS(is_insert=False, is_update=False, is_delete=False, all_mappers=[mapper]))
    av._forget_on_dml(NS(is_insert=False, is_update=True, is_delete=False, all_mappers=[other]))
    await av.alias_view(db, owner)
    assert db.reads == 2, "a select, or an update of another table, leaves it alone"
    av._forget_on_dml(NS(is_insert=False, is_update=True, is_delete=False, all_mappers=[mapper]))
    await av.alias_view(db, owner)
    assert db.reads == 4
