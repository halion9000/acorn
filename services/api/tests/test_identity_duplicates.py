"""Possible duplicate people: the likely-but-uncertain pairs the automatic merge rules leave alone, suggested inside one client only."""

import uuid

from app.services.identity_duplicates import MAX_BUCKET, find_duplicates, local_key, name_key
from app.services.identity_people import Person

A, B = uuid.uuid4(), uuid.uuid4()


def person(tenant, email, name=None, **over):
    return Person(tenant_id=tenant, email=email, display_name=name, **over)


def pairs(people, separate=()):
    return [(p.a.email, p.b.email, p.score, p.label) for p in find_duplicates(people, list(separate))]


def test_a_name_is_reduced_to_what_identifies_a_person():
    assert name_key("Marla Falcon") == "marla falcon"
    assert name_key("Marla Falcon @ PPP") == "marla falcon"
    assert name_key("Marla  Falcon - old account") == "marla falcon"
    assert name_key("José Núñez (contractor)") == "jose nunez"
    assert name_key("Marla") is None, "a first name alone says nothing"
    assert name_key("marla@acme.com") is None, "an address shown as a name is not a name"
    assert name_key(None) is None
    assert local_key("Marla@Acme.com") == "marla"
    assert local_key("admin@acme.com") is None, "a role name is not a person"
    assert local_key("jo@acme.com") is None, "too short"


def test_the_same_name_on_two_domains_of_one_client_is_suggested_with_the_reasons():
    people = [
        person(A, "marla@practicecompliance.com", "Marla Falcon"),
        person(A, "marla@practiceperformance.com", "Marla Falcon @ PPP"),
    ]
    got = find_duplicates(people, [])
    assert len(got) == 1
    pair = got[0]
    assert pair.score == 90 and pair.label == "high", "the same name (60) plus the same name before the @ (30)"
    assert any(r.startswith("The same name: Marla Falcon") for r in pair.reasons)
    assert any("before the @: marla" in r for r in pair.reasons)


def test_nothing_is_suggested_across_clients():
    assert pairs([person(A, "marla@a.com", "Marla Falcon"), person(B, "marla@b.com", "Marla Falcon")]) == []


def test_the_same_name_alone_is_medium_and_the_same_first_name_alone_is_not_enough():
    medium = pairs([person(A, "xq1@a.com", "Marla Falcon"), person(A, "xq2@a.com", "Marla Falcon")])
    assert medium == [("xq1@a.com", "xq2@a.com", 60, "medium")]
    assert (
        pairs([person(A, "alex@a.com", "Alex Kim"), person(A, "alex@b.com", "Alex Park")]) == []
    ), "the same part before the @ alone (30) is not worth showing"


def test_a_name_that_matches_the_other_persons_address_adds_weight_to_a_pair_already_found():
    got = find_duplicates([person(A, "mfalcon@a.com", "Marla Falcon"), person(A, "marla.falcon@b.com", "M Falcon")], [])
    assert got == [], "a pattern alone never makes a pair"
    both = find_duplicates([person(A, "mfalcon@a.com", "Marla Falcon"), person(A, "marla.falcon@b.com", "Marla Falcon")], [])
    assert len(both) == 1 and both[0].score == 60 + 25 + 25
    assert sum("matches the address" in r for r in both[0].reasons) == 2


def test_guests_shared_mailboxes_and_generic_names_are_never_suggested():
    assert pairs([person(A, "a@a.com", "Marla Falcon", kind="guest"), person(A, "b@b.com", "Marla Falcon")]) == []
    assert (
        pairs([person(A, "frontdesk@a.com", "Front Desk", kind="shared"), person(A, "reception@a.com", "Front Desk", kind="shared")]) == []
    )
    assert pairs([person(A, "admin@a.com", "Pat Lee"), person(A, "admin@b.com", "Pat Lee")]) != [], "the same name still counts"
    assert (
        find_duplicates([person(A, "admin@a.com", "Admin"), person(A, "admin@b.com", "Admin")], []) == []
    ), "a generic single word is nobody"
    assert pairs([person(A, "x_partner.com#EXT#@client.onmicrosoft.com", "Marla Falcon"), person(A, "marla@a.com", "Marla Falcon")]) == []


def test_a_pair_the_owner_said_is_separate_is_not_suggested_again_whichever_address_was_named():
    people = [person(A, "marla@a.com", "Marla Falcon", aliases=["marla@a.onmicrosoft.com"]), person(A, "marla@b.com", "Marla Falcon")]
    assert len(find_duplicates(people, [])) == 1
    for x, y in (("marla@a.com", "marla@b.com"), ("marla@b.com", "marla@a.onmicrosoft.com"), ("MARLA@B.COM", "Marla@A.com")):
        assert find_duplicates(people, [(A, x, y)]) == [], (x, y)
    assert len(find_duplicates(people, [(B, "marla@a.com", "marla@b.com")])) == 1, "a mark at another client does not apply"


def test_two_licensed_accounts_are_suggested_but_say_so():
    both = find_duplicates([person(A, "m@a.com", "Marla Falcon", licensed=True), person(A, "mf@b.com", "Marla Falcon", licensed=True)], [])
    assert len(both) == 1 and both[0].both_licensed is True
    one = find_duplicates([person(A, "m@a.com", "Marla Falcon", licensed=True), person(A, "mf@b.com", "Marla Falcon", licensed=False)], [])
    assert one[0].both_licensed is False


def test_a_very_common_name_is_a_guess_not_a_sign_and_the_list_is_strongest_first_and_limited():
    crowd = [person(A, f"john{i}@a.com", "John Smith") for i in range(MAX_BUCKET + 1)]
    assert find_duplicates(crowd, []) == [], "more than a handful of people with one name means it proves nothing"
    small = [person(A, f"john{i}@a.com", "John Smith") for i in range(3)]
    assert len(find_duplicates(small, [])) == 3
    mixed = [
        person(A, "marla@a.com", "Marla Falcon"),
        person(A, "marla@b.com", "Marla Falcon"),
        person(A, "kim@a.com", "Kim Lee"),
        person(A, "kl@a.com", "Kim Lee"),
    ]
    got = find_duplicates(mixed, [])
    assert [p.score for p in got] == sorted((p.score for p in got), reverse=True) and got[0].score == 90
    assert len(find_duplicates(mixed, [], limit=1)) == 1


def test_a_person_already_holding_both_addresses_is_not_a_pair_with_themselves():
    one = person(A, "marla@a.com", "Marla Falcon", aliases=["marla@b.com"])
    assert find_duplicates([one], []) == []


def test_the_endpoint_returns_the_pairs_with_both_people_and_leaves_out_what_the_owner_dismissed(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from app.api.v1.endpoints import identities as ep

    people = [
        person(A, "marla@a.com", "Marla Falcon", client_name="Acme", licensed=True),
        person(A, "marla@b.com", "Marla Falcon @ B", client_name="Acme", licensed=True),
        person(A, "kim@a.com", "Kim Lee", client_name="Acme"),
        person(A, "kl@a.com", "Kim Lee", client_name="Acme"),
    ]
    dismissed = [(A, "kim@a.com", "kl@a.com")]

    async def fake_people(db, owner, client_id):
        return people, {}

    async def fake_scope(db, owner, client_id):
        return [A], {A: "Acme"}

    async def fake_decisions(db, scope):
        return [], dismissed

    monkeypatch.setattr(ep, "_people", fake_people)
    monkeypatch.setattr(ep, "_scope", fake_scope)
    monkeypatch.setattr(ep, "owner_decisions", fake_decisions)
    out = asyncio.run(ep.list_duplicates(SimpleNamespace(tenant_id=uuid.uuid4()), object(), client_id=None, limit=100))
    assert out.total == 1
    item = out.items[0]
    assert (item.a.email, item.b.email, item.client_name, item.confidence, item.both_licensed) == (
        "marla@a.com",
        "marla@b.com",
        "Acme",
        "high",
        True,
    )
    assert item.score == 90 and any("before the @" in r for r in item.reasons)
    assert item.a.client_id == A
