"""The assessment questions from the vCIO Toolbox template: all of them are listed, answered only where a check speaks to them, never guessed, and a person's answer is laid over."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from types import SimpleNamespace as NS

import pytest
from app.services.assessment_questions import QUESTIONS
from app.services.assessment_review import CHECK_ANSWERS, GOOGLE_PEOPLE_FRESH_DAYS, assessment_answers, google_two_step_answer
from app.services.review_overrides import clean_answer, merge_assess
from fastapi import HTTPException


def by_question(answers):
    return {a.question: a for a in answers}


def test_all_145_template_questions_are_listed_in_order_under_their_sheet_and_group():
    answers = assessment_answers({})
    assert len(answers) == 145 == len(QUESTIONS)
    assert [a.question for a in answers] == [q for _s, _g, q in QUESTIONS]
    assert {a.sheet for a in answers} == {
        "Administrative",
        "Network and infrastructure",
        "Servers",
        "Workstations",
        "Cybersecurity and risk",
        "Backup and disaster recovery",
        "Google Workspace",
    }
    assert all(len(a.question) <= 400 for a in answers), "a question is its own answer key, which holds 400 characters"
    assert len({a.question for a in answers}) == 145


def test_with_no_checks_every_question_needs_a_person_and_nothing_is_invented():
    assert {a.status for a in assessment_answers({})} == {"needs_person"}
    assert all(a.evidence == "" for a in assessment_answers({}))


def test_every_mapping_points_at_exactly_one_question():
    from app.services.assessment_review import _question

    for prefix, keys, _scope in CHECK_ANSWERS:
        assert _question(prefix) and keys


def test_a_check_the_client_has_answers_the_question_it_speaks_to_and_says_which_check():
    out = by_question(
        assessment_answers(
            {
                "ninjaone_patching": {"key": "ninjaone_patching", "status": "partly", "evidence": "3 of 40 Windows machines are behind"},
                "sat_training_completion": {"key": "sat_training_completion", "status": "met", "evidence": "96% completed"},
                "liongard_disk_encryption": {"key": "liongard_disk_encryption", "status": "not_met", "evidence": "4 laptops unencrypted"},
            }
        )
    )
    patch = out["Are Windows Updates for security patches configured and enabled?"]
    assert patch.status == "partly" and "From ninjaone_patching" in patch.evidence and "3 of 40" in patch.evidence
    assert out["Are all users up to date on their training?"].status == "met"
    assert out["Are all firm-issued Windows Laptops encrypted?"].status == "not_met"
    assert out["Are users clicking on phishing emails?"].status == "needs_person", "no phishing-simulation check, no answer"


def test_the_servers_question_is_answered_by_the_servers_own_patching_check_and_never_by_the_all_machines_one():
    servers = "Are all Windows Server Operating Systems up to the latest service pack for their respective OS?"
    workstations = "Are all workstations up to the latest service pack and updates for their respective OS?"
    all_machines = {"key": "ninjaone_patching", "status": "partly", "evidence": "1 of 22 Windows machines behind"}
    only_all = by_question(assessment_answers({"ninjaone_patching": all_machines}))
    assert only_all[servers].status == "needs_person", "a client with no server check gets no answer about its servers"
    assert only_all[workstations].status == "partly"
    late = {
        "key": "ninjaone_server_patching",
        "status": "not_met",
        "evidence": "1 of 2 Windows servers have a critical or important update",
    }
    both = by_question(assessment_answers({"ninjaone_patching": all_machines, "ninjaone_server_patching": late}))
    assert both[servers].status == "not_met"
    assert "From ninjaone_server_patching" in both[servers].evidence and "1 of 2 Windows servers" in both[servers].evidence
    assert both[workstations].status == "partly", "the workstation question keeps its own check"


def test_the_two_super_administrator_questions_each_read_their_own_google_check():
    at_least_two = "Does more than one Super Admin account exist"
    over_four = "Is there more than 4 Super Admin accounts existing in the account"
    nothing = by_question(
        assessment_answers(
            {"threatmate_google_admins": {"key": "threatmate_google_admins", "status": "met", "evidence": "All 3 have 2-Step"}}
        )
    )
    assert (
        nothing[at_least_two].status == nothing[over_four].status == "needs_person"
    ), "the 2-Step check says nothing about how many there are"
    one_admin = by_question(
        assessment_answers(
            {
                "threatmate_google_super_admin_min": {
                    "key": "threatmate_google_super_admin_min",
                    "status": "not_met",
                    "evidence": "1 Google super administrator",
                },
                "threatmate_google_super_admin_max": {
                    "key": "threatmate_google_super_admin_max",
                    "status": "met",
                    "evidence": "1 Google super administrator; no more than 4",
                },
            }
        )
    )
    assert one_admin[at_least_two].status == "not_met" and "From threatmate_google_super_admin_min" in one_admin[at_least_two].evidence
    assert one_admin[over_four].status == "met", "one administrator fails the first question and passes the second"
    assert "no more than 4" in one_admin[over_four].evidence, "Met beside a question worded 'more than 4' must say what it means"


def test_the_first_check_the_client_has_wins_and_an_unusable_status_is_ignored():
    q = "Has a managed endpoint security been deployed to protect against virus, malware, and host intrusion"
    both = by_question(
        assessment_answers(
            {
                "huntress_protection": {"status": "met", "evidence": "all protected"},
                "ninjaone_antivirus": {"status": "not_met", "evidence": "x"},
            }
        )
    )
    assert both[q].status == "met" and "huntress_protection" in both[q].evidence
    only_second = by_question(
        assessment_answers(
            {
                "huntress_protection": {"status": "unknown", "evidence": ""},
                "ninjaone_antivirus": {"status": "partly", "evidence": "2 without"},
            }
        )
    )
    assert only_second[q].status == "partly" and "ninjaone_antivirus" in only_second[q].evidence


def test_public_rdp_is_ruled_out_by_a_clean_exposure_scan_and_named_by_a_finding_but_other_findings_say_nothing():
    q = "Is the Public port 3389 (Remote Desktop) exposed allowing remote access to servers and/or desktops?"
    assert (
        by_question(assessment_answers({"threatmate_external_exposure": {"status": "met", "evidence": "No exposed services"}}))[q].status
        == "met"
    )
    bad = by_question(
        assessment_answers({"threatmate_external_exposure": {"status": "not_met", "evidence": "Exposed RDP on 203.0.113.9"}})
    )[q]
    assert bad.status == "not_met" and "RDP" in bad.evidence
    other = by_question(assessment_answers({"threatmate_external_exposure": {"status": "not_met", "evidence": "Open FTP on one host"}}))[q]
    assert other.status == "needs_person"


def test_a_typed_status_replaces_the_worked_out_one_and_keeps_it_and_a_question_can_be_marked_not_applicable():
    answers = assessment_answers({"sat_training_completion": {"status": "met", "evidence": "96%"}})
    train = "Are all users up to date on their training?"
    ups = "Is there UPS onsite?"
    rows = [
        NS(section="assess", key=train, status="partly", note="two new hires", updated_at=None),
        NS(section="assess", key=ups, status="not_applicable", note=None, updated_at=None),
        NS(section="m365", key=ups, status="met", note=None, updated_at=None),  # another section's row never applies
    ]
    out = by_question(merge_assess(answers, rows))
    assert out[train].status == "partly" and out[train].manual and out[train].auto_status == "met" and out[train].note == "two new hires"
    assert out[ups].status == "not_applicable" and out[ups].manual and out[ups].auto_status == "needs_person"


def test_the_assess_section_accepts_its_statuses_and_refuses_others():
    for st in ("met", "partly", "not_met", "needs_person", "not_applicable"):
        assert clean_answer("assess", "Is there UPS onsite?", st, None, None)[0] == st
    with pytest.raises(HTTPException):
        clean_answer("assess", "Is there UPS onsite?", "seen", None, None)
    with pytest.raises(HTTPException):
        clean_answer("assess", "Is there UPS onsite?", "met", "a typed answer", None)  # only the technology questions take one


# ---- Google 2-Step enforcement, from the stored people ---------------------------------------------------------------------------------------------------

TWO_STEP = "Do you ensure 2-Step Verification (Multi-Factor Authentication) is enforced for all users"
T0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def person(per_user=None, *, source="threatmate", enabled=True, registered=False, days_old=1):
    return SimpleNamespace(
        source=source, enabled=enabled, per_user=per_user, registered=registered, refreshed_at=T0 - timedelta(days=days_old)
    )


def two_step(people):
    return by_question(assessment_answers({}, people=people, now=T0))[TWO_STEP]


def test_the_question_is_in_the_template_exactly_once():
    assert [q for _, _, q in QUESTIONS].count(TWO_STEP) == 1


def test_two_step_enforced_for_every_google_account_is_met_some_is_partly_and_none_is_not_met():
    everyone = two_step([person("enforced"), person("enforced")])
    assert everyone.status == "met" and "enforced for 2 of 2 Google accounts." in everyone.evidence
    some = two_step([person("enforced"), person(registered=True), person()])
    assert some.status == "partly"
    assert "enforced for 1 of 3 Google accounts; 1 of the other 2 have signed up for it without it being required." in some.evidence
    nobody = two_step([person(registered=True), person(registered=True)])
    assert nobody.status == "not_met", "everyone signed up is still not enforcement"
    assert "enforced for 0 of 2" in nobody.evidence


def test_only_live_google_people_count_and_an_empty_list_never_answers():
    assert two_step([]).status == "needs_person"
    assert by_question(assessment_answers({}))[TWO_STEP].status == "needs_person", "called the old way, with checks only"
    microsoft = person("enforced", source="cipp")
    suspended = person(enabled=False)
    old = person(days_old=GOOGLE_PEOPLE_FRESH_DAYS + 1)
    assert (
        two_step([microsoft, suspended, old]).status == "needs_person"
    ), "Microsoft people, suspended accounts and a list not refreshed for over a week say nothing"
    mixed = two_step([person("enforced"), microsoft, suspended, old])
    assert mixed.status == "met" and "1 of 1 Google accounts" in mixed.evidence
    assert (
        google_two_step_answer([person("enforced", days_old=GOOGLE_PEOPLE_FRESH_DAYS)], T0) is not None
    ), "exactly a week old still counts"


def test_the_google_admin_two_step_check_does_not_answer_the_all_users_question():
    checks = {
        "threatmate_google_admins": {
            "key": "threatmate_google_admins",
            "status": "met",
            "evidence": "All 3 super administrators have 2-Step",
        }
    }
    assert by_question(assessment_answers(checks))[TWO_STEP].status == "needs_person"
