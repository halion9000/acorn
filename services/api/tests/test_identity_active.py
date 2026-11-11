"""Active identities: a licensed Microsoft 365 or Google account that is not a guest and is not disabled. The tile and the list it opens must agree, and everyone is still counted under All Identities."""

from app.api.v1.endpoints import identities as ep
from app.services import identity_people as ip

from tests.test_identity_people import NOW, A, ms, src


def build():
    return ip.build_people(
        {A: "Acme"},
        [
            ms(A, "member@acme.com"),  # licensed, member, enabled: active
            ms(A, "guest@partner.com", user_type="Guest"),  # licensed guest: no
            ms(A, "off@acme.com", enabled=False),  # licensed but disabled: no
            ms(A, "nolicence@acme.com", licensed=False),  # no licence: no
        ],
        [
            src(
                A, "google-workspace", "g.on@acme.com", enabled=True, details={"directory": True, "licensed": True}
            ),  # a licensed Google account: active
            src(A, "google-workspace", "g.free@acme.com", enabled=True, details={"directory": True, "licensed": False}),  # not licensed: no
            src(A, "google-workspace", "g.off@acme.com", enabled=False, details={"directory": True, "licensed": True}),  # disabled: no
            src(A, "huntress", "tool.only@acme.com", enabled=True),  # a tool that says nothing about licences: no
        ],
        NOW,
    )


def emails(people):
    return sorted(p.email for p in people)


def test_only_a_licensed_account_that_is_not_a_guest_and_not_disabled_is_active():
    people = build()
    assert emails([p for p in people if ip.is_active(p)]) == ["g.on@acme.com", "member@acme.com"]


def test_the_tile_count_and_the_list_it_opens_hold_exactly_the_same_people():
    people = build()
    listed = ip.filter_people(people, active=True)
    assert ep.summarize(people).active == len(listed) == 2
    assert emails(listed) == ["g.on@acme.com", "member@acme.com"]


def test_everyone_is_still_counted_under_all_identities_and_the_filter_combines_with_others():
    people = build()
    assert ep.summarize(people).total == len(people) == 8
    assert emails(ip.filter_people(people, active=True, kind="guest")) == [], "a guest is never active"
    assert emails(ip.filter_people(people, active=True, search="g.on")) == ["g.on@acme.com"]


def test_an_account_no_tool_says_is_disabled_is_not_called_disabled():
    people = ip.build_people(
        {A: "Acme"}, [], [src(A, "google-workspace", "quiet@acme.com", enabled=None, details={"directory": True, "licensed": True})], NOW
    )
    assert [p.email for p in people if ip.is_active(p)] == ["quiet@acme.com"]
