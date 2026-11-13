"""vCIO Risk Scoring answers filled in from the integrations: every Client Review question has its counterpart here, a reading becomes the right answer whichever way the question is
worded, and an answer a person set is never replaced."""

from types import SimpleNamespace as Row

from app.services import m365_review, tech_stack
from app.services import vcio_risk_scoring as rs
from app.services.assessment_questions import QUESTIONS as ASSESS_QUESTIONS

RDP = "Is the Public port 3389 (Remote Desktop) exposed allowing remote access to servers and/or desktops?"
PATCHING = "Are Windows Updates for security patches configured and enabled?"


def assess(question, status, evidence="", **over):
    return Row(question=question, status=status, evidence=evidence, manual=False, note=None, **over)


def tech(key, status, suggested=None, evidence=""):
    question = next(q for k, _g, q in tech_stack.QUESTIONS if k == key)
    return Row(question=question, status=status, suggested=suggested, evidence=evidence, manual=False, note=None)


def test_every_client_review_question_has_exactly_one_counterpart_here():
    by_text = rs.questions_by_text()
    assert len(by_text) == 330, "no two questions of the library read the same"
    missing = [
        q
        for q in [
            *(q for _s, _g, q in ASSESS_QUESTIONS),
            *(q for _g, q in m365_review.QUESTIONS),
            *(q for _k, _g, q in tech_stack.QUESTIONS),
        ]
        if rs._text_key(q) not in by_text
    ]
    assert missing == [], "a Client Review question with no counterpart would silently never be filled in"
    assert len(ASSESS_QUESTIONS) + len(m365_review.QUESTIONS) + len(tech_stack.QUESTIONS) == 268


def test_met_is_the_good_answer_whichever_way_the_question_is_worded_and_needs_person_is_no_answer():
    by_text = rs.questions_by_text()
    rdp, patching = by_text[rs._text_key(RDP)], by_text[rs._text_key(PATCHING)]
    assert (rdp["good"], patching["good"]) == ("No", "Yes")
    assert [rs.answer_from_status(patching, s) for s in ("met", "partly", "not_met", "not_applicable", "needs_person", "")] == [
        "Yes",
        "Partial",
        "No",
        "N/A",
        None,
        None,
    ]
    assert [rs.answer_from_status(rdp, s) for s in ("met", "not_met")] == [
        "No",
        "Yes",
    ], "RDP not exposed is the practice in place: the answer is No"
    found = rs.answers_from_review(
        [
            assess(RDP, "not_met", "ThreatMate finds port 3389 open"),
            assess(PATCHING, "met", "From ninjaone_patching. 40 of 40 patched"),
            assess("Is the UPS tested?", "met"),
        ],
        [],
        [],
    )
    assert found == {
        rdp["id"]: {"answer": "Yes", "evidence": "ThreatMate finds port 3389 open"},
        patching["id"]: {"answer": "Yes", "evidence": "From ninjaone_patching. 40 of 40 patched"},
    }
    assert rs.answers_from_review([assess(PATCHING, "needs_person")], [], []) == {}


def test_a_tech_stack_reading_is_preferred_for_the_standard_vendor_alternative_for_another_and_none_when_the_tool_shows_nothing():
    found = rs.answers_from_review(
        [],
        [],
        [
            tech("firewall", "seen", "Meraki MX68", "1 firewall: Meraki MX68"),
            tech("switch", "seen", "Aruba 2930F"),
            tech("wireless", "not_seen", "None seen", "No access point is listed"),
            tech("backup_isp", "unknown"),
        ],
    )
    by_id = rs.questions_by_id()
    assert {by_id[k]["text"][:24]: v for k, v in found.items()} == {
        "What is the client Firew": {"answer": "Preferred", "evidence": "1 firewall: Meraki MX68", "vendor": "Meraki MX68"},
        "What Switch technology i": {"answer": "Alternative", "evidence": "From Client Review.", "vendor": "Aruba 2930F"},
        "What wireless system is ": {"answer": "None", "evidence": "No access point is listed"},
    }
    vendor_q = next(q for q in rs.library() if q["type"] == "vendor" and q["preferred"] == "Huntress")
    assert rs.answer_from_tech(vendor_q, "seen", "Huntress") == ("Preferred", "Huntress")
    assert rs.answer_from_tech(vendor_q, "seen", "SentinelOne") == ("Alternative", "SentinelOne")
    assert rs.answer_from_tech(vendor_q, "seen", None) == (None, None), "seen with no product named says nothing about which vendor"


def test_an_answer_typed_in_client_review_comes_across_and_says_that_it_was_typed():
    row = assess(PATCHING, "not_met", "From ninjaone_patching. 3 of 40 behind")
    row.manual, row.note = True, "client confirmed WSUS is off"
    [only] = rs.answers_from_review([row], [], []).values()
    assert only == {
        "answer": "No",
        "evidence": "Typed in Client Review: client confirmed WSUS is off. From ninjaone_patching. 3 of 40 behind",
    }


def test_autofill_never_replaces_a_hand_answer_updates_its_own_and_takes_back_one_the_integrations_no_longer_give():
    found = {
        "ADM-001": {"answer": "Yes", "evidence": "e1"},
        "NET-002": {"answer": "No", "evidence": "clean scan"},
        "TS-001": {"answer": "Preferred", "vendor": "Meraki MX68", "evidence": "e3"},
    }
    stored = {"ADM-001": {"answer": "No", "note": "they told us"}, "ADM-002": {"note": "ask Dana"}}
    out, counts = rs.apply_autofill(stored, found)
    assert out["ADM-001"] == {"answer": "No", "note": "they told us"}, "set by hand: left exactly as it was"
    assert out["NET-002"] == {"answer": "No", "source": "auto", "evidence": "clean scan"}
    assert out["TS-001"] == {"answer": "Preferred", "vendor": "Meraki MX68", "source": "auto", "evidence": "e3"}
    assert out["ADM-002"] == {"note": "ask Dana"}
    assert counts == {"filled": 2, "changed": 0, "kept_by_hand": 1, "cleared": 0, "answered_by_integrations": 3}
    # A second run: one reading changed, one went away, and a note added to an auto answer stays with it.
    out["NET-002"]["note"] = "checked with the ISP"
    again, counts = rs.apply_autofill(
        out, {"NET-002": {"answer": "Yes", "evidence": "3389 open"}, "ADM-001": {"answer": "Yes", "evidence": "e1"}}
    )
    assert again["NET-002"] == {"note": "checked with the ISP", "answer": "Yes", "source": "auto", "evidence": "3389 open"}
    assert "TS-001" not in again, "the integrations say nothing for it now, so the old auto-answer is not left looking current"
    assert counts == {"filled": 0, "changed": 1, "kept_by_hand": 1, "cleared": 1, "answered_by_integrations": 2}
    same, counts = rs.apply_autofill(again, {"NET-002": {"answer": "Yes", "evidence": "3389 open"}})
    assert counts["filled"] == 0 and counts["changed"] == 0 and same["NET-002"]["note"] == "checked with the ISP"


def test_an_auto_answer_scores_like_any_other():
    out, _ = rs.apply_autofill({}, {"ADM-001": {"answer": "Yes", "evidence": "e"}})
    card = rs.scorecard({k: v["answer"] for k, v in out.items()})
    assert card["answered"] == 1 and card["overall"] == 1.0
