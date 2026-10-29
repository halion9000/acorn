"""Google Workspace people (read by ThreatMate) beside Microsoft 365 people in the Multi-Factor counts: each directory is judged on its own terms."""

from __future__ import annotations

from types import SimpleNamespace

from app.api.v1.endpoints.identity import counts_for_mfa
from app.services.mfa_registration import directory_of, known_by_source, microsoft_rows, second_factor


def person(
    source="cipp",
    upn="a@x.test",
    *,
    registered=False,
    per_user=None,
    ca=False,
    sd=False,
    admin=False,
    enabled=True,
    licensed=True,
    methods=None,
):
    return SimpleNamespace(
        source=source,
        upn=upn,
        admin=admin,
        enabled=enabled,
        licensed=licensed,
        user_type="Member",
        registered=registered,
        capable=registered,
        per_user=per_user,
        ca_enforced=ca,
        security_defaults=sd,
        methods=methods,
    )


def google(upn, *, enrolled, enforced, admin=False):
    return person(
        "threatmate",
        upn,
        registered=enrolled,
        per_user="enforced" if enforced else None,
        admin=admin,
        methods="2-Step Verification" if enrolled else None,
    )


def test_a_google_only_client_is_counted_by_enrolment_and_enforcement():
    users = [
        google("a@g.test", enrolled=True, enforced=True),  # covered
        google("b@g.test", enrolled=True, enforced=False),  # signed up, nothing requires it
        google("c@g.test", enrolled=False, enforced=False, admin=True),  # none, and an administrator
        google("d@g.test", enrolled=False, enforced=True),  # required but not enrolled: still none
    ]
    c = counts_for_mfa(users)
    assert (c["people"], c["with_mfa"], c["not_required"], c["without_mfa"], c["admins_without_mfa"]) == (4, 1, 1, 2, 1)
    assert c["registration_unknown"] == 0, "Google always says who enrolled"


def test_microsoft_people_with_no_registration_report_are_still_judged_by_what_is_required_when_google_people_are_added():
    microsoft = [
        person(sd=True, upn="m1@x.test"),
        person(sd=True, upn="m2@x.test"),
    ]  # security defaults, no registrations reported (no Entra P1)
    only_microsoft = counts_for_mfa(microsoft)
    assert (only_microsoft["with_mfa"], only_microsoft["without_mfa"], only_microsoft["registration_unknown"]) == (2, 0, 1)
    both = counts_for_mfa(microsoft + [google("g@g.test", enrolled=True, enforced=True)])
    assert (both["people"], both["with_mfa"], both["without_mfa"]) == (
        3,
        3,
        0,
    ), "the Google row's registration must not flip the Microsoft people to 'no second factor'"
    assert both["registration_unknown"] == 1, "the Microsoft side still cannot say who registered"


def test_each_source_is_judged_on_its_own_report():
    users = [person(registered=True, upn="m@x.test"), google("g@g.test", enrolled=False, enforced=False)]
    known = known_by_source(users)
    assert known == {"cipp": True, "threatmate": True}
    assert second_factor(users[0], known) and not second_factor(users[1], known)


def test_only_microsoft_rows_answer_the_microsoft_questions_and_each_row_names_its_directory():
    users = [person(upn="m@x.test"), google("g@g.test", enrolled=True, enforced=True)]
    assert [u.upn for u in microsoft_rows(users)] == ["m@x.test"]
    assert [directory_of(u) for u in users] == ["Microsoft 365", "Google Workspace"]
    assert directory_of(SimpleNamespace(upn="x")) == "Microsoft 365", "a row with no source is Microsoft's"
