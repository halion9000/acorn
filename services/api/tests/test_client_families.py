"""Client families: who is linked under one parent company (pure helpers)."""

import uuid

from app.services import client_families as cf


def ids(n):
    return [uuid.uuid4() for _ in range(n)]


def test_family_map_and_siblings():
    f1, f2 = ids(2)
    a, b, c, d = ids(4)
    m = cf.family_map([(f1, a), (f1, b), (f2, c)])
    assert cf.same_family(m, a, b) and not cf.same_family(m, a, c)
    assert not cf.same_family(m, a, a), "a client is not its own sibling"
    assert not cf.same_family(m, c, d), "a client in no family has no siblings"
    assert cf.siblings(m, a) == {b} and cf.siblings(m, c) == set() and cf.siblings(m, d) == set()


def test_members_must_be_the_owners_clients_and_not_in_another_family():
    f1, f2 = ids(2)
    a, b, stranger = ids(3)
    taken = {a: f1}
    assert cf.clean_members([a, a, b], {a, b}, taken, f1) == ([a, b], None), "repeats are dropped; its own members stay allowed"
    members, why = cf.clean_members([a], {a, b}, taken, f2)
    assert members == [] and "another family" in why
    members, why = cf.clean_members([stranger], {a, b}, taken, f1)
    assert members == [] and "not one of yours" in why
