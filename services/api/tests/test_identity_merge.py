"""Folding the several addresses of one human into one person: each automatic rule, what it must NOT join, the owner's own merges, and what the merged person shows."""

import asyncio
import contextlib
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.v1.endpoints import identity_merges as ep
from app.services import identity_people as ip
from fastapi import HTTPException

from tests.test_identity_people import NOW, ms, src

A, B = uuid.uuid4(), uuid.uuid4()
NAMES = {A: "Acme", B: "Other"}


def build(users=(), sources=(), merges=None, separate=None):
    return ip.build_people(NAMES, list(users), list(sources), NOW, merges=merges, separate=separate)


def one(people, address):
    return next(p for p in people if address in p.addresses)


def emails(people):
    return sorted(p.email for p in people)


# ---- the automatic rules -----------------------------------------------------------------------------------------------------------------------------------


def test_a_display_name_that_is_another_existing_address_joins_the_two():
    people = build([ms(A, "bmoore@grcooling.com", display_name="brandon@grcooling.com"), ms(A, "brandon@grcooling.com", display_name="Brandon Moore")])
    assert len(people) == 1
    p = people[0]
    assert set(p.addresses) == {"bmoore@grcooling.com", "brandon@grcooling.com"}
    assert p.display_name == "Brandon Moore", "a name that is just an address is not the name to show"
    assert list(p.alias_reasons.values()) == ["its name is this address"]


def test_a_display_name_that_is_an_address_nobody_has_joins_nothing():
    assert len(build([ms(A, "bmoore@grcooling.com", display_name="brandon@grcooling.com")])) == 1
    assert len(build([ms(A, "x@acme.com", display_name="y@acme.com"), ms(A, "z@acme.com")])) == 2


def test_a_guest_sign_in_name_joins_the_real_address_when_it_exists_and_not_when_it_does_not():
    guest = "adrian.rodriguez_elpasochildrens.org#ext#@chatexas.onmicrosoft.com"
    both = build([ms(A, guest, user_type="Guest"), ms(A, "adrian.rodriguez@elpasochildrens.org")])
    assert len(both) == 1 and set(both[0].addresses) == {guest, "adrian.rodriguez@elpasochildrens.org"}
    assert both[0].email == "adrian.rodriguez@elpasochildrens.org", "the real address is the one shown"
    assert len(build([ms(A, guest, user_type="Guest")])) == 1


def test_a_system_prefix_on_a_microsoft_address_joins_the_plain_one():
    people = build([ms(A, "3fc24b428b1340e981aed11fd961b331jordan.welling@tecovas.onmicrosoft.com"), ms(A, "jordan.welling@tecovas.onmicrosoft.com")])
    assert len(people) == 1 and people[0].email == "jordan.welling@tecovas.onmicrosoft.com"


def test_a_microsoft_address_joins_the_one_real_address_with_the_same_name_and_the_real_one_is_shown():
    people = build([ms(A, "adam@tecovas.onmicrosoft.com"), ms(A, "adam@tecovas.com")])
    assert len(people) == 1 and people[0].email == "adam@tecovas.com" and people[0].aliases == ["adam@tecovas.onmicrosoft.com"]


def test_two_real_domains_with_the_same_name_are_not_joined_automatically_so_the_microsoft_one_does_not_pick_between_them():
    people = build([ms(A, "alix@fbgfarms.com"), ms(A, "alix@ffarms.com"), ms(A, "alix@fredericksburgfarms.onmicrosoft.com")])
    assert len(people) == 3, "ambiguous: left for the owner"


def test_a_name_like_admin_or_support_is_never_joined_by_name_alone():
    people = build([ms(A, "admin@acme.onmicrosoft.com"), ms(A, "admin@acme.com"), ms(A, "support@acme.onmicrosoft.com"), ms(A, "support@acme.com")])
    assert len(people) == 4


def test_a_very_short_name_is_not_joined():
    assert len(build([ms(A, "jo@acme.onmicrosoft.com"), ms(A, "jo@acme.com")])) == 2


def test_nobody_is_ever_joined_across_clients():
    people = build([ms(A, "adam@tecovas.onmicrosoft.com"), ms(B, "adam@tecovas.com")])
    assert len(people) == 2


def test_a_shared_mailbox_is_not_joined_by_any_rule():
    shared = src(A, "cipp", "adam@acme.com", kind="shared")
    assert len(build([ms(A, "adam@acme.onmicrosoft.com")], [shared])) == 2


# ---- what the merged person shows --------------------------------------------------------------------------------------------------------------------------


def test_the_merged_person_carries_every_tool_of_every_address_once_and_the_facts_that_matter():
    users = [ms(A, "adam@tecovas.com", admin=False, enabled=True), ms(A, "adam@tecovas.onmicrosoft.com", admin=True, enabled=False)]
    sources = [src(A, "datto-saas", "adam@tecovas.com"), src(A, "huntress", "adam@tecovas.onmicrosoft.com"), src(A, "huntress", "adam@tecovas.onmicrosoft.com")]
    (p,) = build(users, sources)
    assert p.vendors == ["cipp", "datto-saas", "huntress"]
    assert p.admin is True, "an administrator under any address is an administrator"
    assert p.enabled is True, "one enabled address means the person can sign in"
    assert len({(s.vendor, s.external_id) for s in p.sources}) == len(p.sources)


def test_a_person_known_to_one_tool_per_address_becomes_known_to_both():
    before = build([ms(A, "adam@tecovas.com")], [])
    assert one(before, "adam@tecovas.com").vendors == ["cipp"]
    (p,) = build([ms(A, "adam@tecovas.onmicrosoft.com")], [src(A, "dropsuite", "adam@tecovas.com", details={"last_backup": (NOW - timedelta(hours=2)).isoformat(), "errors": 0})])
    assert p.vendors == ["cipp", "dropsuite"] and len(p.backups) == 1, "the backup of one address counts for the person"


def test_an_open_alert_naming_any_address_counts_once_for_the_person():
    people = build([ms(A, "adam@tecovas.com"), ms(A, "adam@tecovas.onmicrosoft.com")])
    alert = lambda addrs, n: type("Al", (), {"tenant_id": A, "affected_users": addrs, "created_at": NOW - timedelta(minutes=n), "severity": "high", "raw_event": {}, "connector_type": None, "status": "new"})()  # noqa: E731
    alerts = [alert(["adam@tecovas.onmicrosoft.com"], 1), alert(["adam@tecovas.com", "adam@tecovas.onmicrosoft.com"], 2)]
    by_key = ip.attach_alerts(people, alerts)
    assert people[0].open_alerts == 2 and len(by_key[people[0].key]) == 2


def test_a_search_for_any_address_finds_the_person():
    people = build([ms(A, "adam@tecovas.com"), ms(A, "adam@tecovas.onmicrosoft.com")])
    assert len(ip.filter_people(people, search="onmicrosoft")) == 1


def test_the_summary_counts_people_not_addresses():
    from app.api.v1.endpoints.identities import summarize

    people = build([ms(A, "adam@tecovas.com"), ms(A, "adam@tecovas.onmicrosoft.com"), ms(A, "eve@tecovas.com")])
    assert summarize(people).total == 2


# ---- the owner's decisions ---------------------------------------------------------------------------------------------------------------------------------


def test_a_hand_merge_joins_two_addresses_no_rule_would():
    people = build([ms(A, "brandon.moore@acme.com"), ms(A, "bmoore@acme.com")], merges=[(A, "bmoore@acme.com", "brandon.moore@acme.com")])
    assert len(people) == 1 and list(people[0].alias_reasons.values()) == ["merged by hand"]
    assert len(build([ms(A, "brandon.moore@acme.com"), ms(A, "bmoore@acme.com")])) == 2


def test_not_the_same_person_stops_a_rule_from_joining_them_and_a_hand_merge_still_wins_over_a_stale_mark():
    users = [ms(A, "adam@tecovas.com"), ms(A, "adam@tecovas.onmicrosoft.com")]
    assert len(build(users, separate=[(A, "adam@tecovas.com", "adam@tecovas.onmicrosoft.com")])) == 2
    assert len(build(users, merges=[(A, "adam@tecovas.com", "adam@tecovas.onmicrosoft.com")], separate=[(A, "adam@tecovas.com", "adam@tecovas.onmicrosoft.com")])) == 1


def test_a_mark_holds_even_when_a_third_address_would_have_joined_them_through_a_chain():
    users = [ms(A, "adam@tecovas.com", display_name="adam2@tecovas.com"), ms(A, "adam2@tecovas.com"), ms(A, "adam2@tecovas.onmicrosoft.com")]
    # adam@ ~ adam2@ (name), adam2@ ~ adam2@...onmicrosoft (same name): all one, until the owner says adam@ is not the onmicrosoft one
    assert len(build(users)) == 1
    marked = build(users, separate=[(A, "adam2@tecovas.onmicrosoft.com", "adam@tecovas.com"), (A, "adam2@tecovas.onmicrosoft.com", "adam2@tecovas.com")])
    assert sorted(len(p.addresses) for p in marked) == [1, 2]
    assert not any({"adam2@tecovas.onmicrosoft.com", "adam@tecovas.com"} <= set(p.addresses) for p in marked)


# ---- the routes --------------------------------------------------------------------------------------------------------------------------------------------

OWNER = uuid.uuid4()
USER = type("U", (), {"tenant_id": OWNER, "user_id": uuid.uuid4()})()


class Fake:
    def __init__(self):
        self.added, self.commits, self.deletes = [], 0, 0
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, *_a, **_k):
        self.deletes += 1
        return MagicMock()

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


@pytest.fixture
def wired(monkeypatch):
    people = build([ms(A, "brandon.moore@acme.com"), ms(A, "bmoore@acme.com"), ms(A, "adam@tecovas.com"), ms(A, "adam@tecovas.onmicrosoft.com")])
    monkeypatch.setattr(ep, "_scope", AsyncMock(return_value=([A], {A: "Acme"})))
    monkeypatch.setattr(ep, "_as", lambda db, owner, tid: contextlib.nullcontext())
    monkeypatch.setattr(ep, "_people", AsyncMock(return_value=(people, {})))
    audit = AsyncMock()
    monkeypatch.setattr(ep, "emit_audit", audit)
    return audit


def run(coro):
    return asyncio.run(coro)


def merge(db, a, b):
    return run(ep.merge_people_by_hand(ep.MergeBody(client_id=A, email=a, with_email=b), MagicMock(), USER, db))


def test_a_merge_stores_one_sorted_decision_and_audits_it(wired):
    db = Fake()
    out = merge(db, "bmoore@acme.com", "brandon.moore@acme.com")
    row = db.added[0]
    assert (row.kind, row.tenant_id) == ("merge", A) and row.address_a < row.address_b
    assert {row.address_a, row.address_b} == {"bmoore@acme.com", "brandon.moore@acme.com"} and db.commits == 1
    assert wired.await_args.kwargs["action"] == "identities:merged" and out.kind == "merge"


def test_merging_a_person_with_themselves_or_with_someone_unknown_is_refused(wired):
    for a, b, code in [("adam@tecovas.com", "adam@tecovas.onmicrosoft.com", 409), ("adam@tecovas.com", "nobody@acme.com", 404), ("adam@tecovas.com", "not an address", 422)]:
        db = Fake()
        with pytest.raises(HTTPException) as e:
            merge(db, a, b)
        assert e.value.status_code == code and db.added == [] and db.commits == 0, (a, b)


def test_not_the_same_person_marks_the_address_against_every_other_address_of_the_group(wired):
    db = Fake()
    out = run(ep.say_not_the_same_person(ep.SeparateBody(client_id=A, email="adam@tecovas.onmicrosoft.com", from_email="adam@tecovas.com"), MagicMock(), USER, db))
    assert out.kind == "separate" and len(db.added) == 1
    assert db.added[0].kind == "separate" and db.added[0].address_a < db.added[0].address_b
    assert wired.await_args.kwargs["action"] == "identities:separated"


def test_the_routes_need_alerts_write():
    from app.main import app
    from route_introspect import required_permissions, walk_routes

    found = {(m, p.replace("/api/v1", "", 1)): r for p, r in walk_routes(app.routes) for m in r.methods}
    for path in ("/identities/merges", "/identities/merges/separate"):
        assert set(required_permissions(found[("POST", path)])) == {"alerts:write"}
