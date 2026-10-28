"""The assessment questions from the vCIO Toolbox template: all of them are listed, answered only where a check speaks to them, never guessed, and a person's answer is laid over."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from app.services.assessment_questions import QUESTIONS
from app.services.assessment_review import CHECK_ANSWERS, assessment_answers
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
