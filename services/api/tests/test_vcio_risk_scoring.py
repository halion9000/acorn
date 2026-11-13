"""vCIO Risk Scoring: the maths of Live Oak's scoring workbook, checked by hand on real questions of its library."""

import pytest
from app.services import vcio_risk_scoring as rs

# Real ids of the library. ADM-001 is High with good answer Yes; NET-001 is Medium with good answer No; NET-002 is Critical with good answer No (exposed RDP); TS-001 is a vendor question.
HIGH_YES, MEDIUM_NO, CRITICAL_NO, VENDOR = "ADM-001", "NET-001", "NET-002", "TS-001"


def category(card, name):
    return next(c for c in card["categories"] if c["name"] == name)


def test_the_library_is_the_workbooks_330_questions_each_complete_and_with_an_id_of_its_own():
    qs = rs.library()
    assert len(qs) == 330 and len({q["id"] for q in qs}) == 330
    assert {q["category"] for q in qs} == set(rs.CATEGORY_ORDER)
    assert {q["severity"] for q in qs} <= set(rs.SEVERITIES) and {q["csf_function"] for q in qs} <= set(rs.CSF_ORDER)
    assert {q["type"] for q in qs} == {"yesno", "vendor"} and {q["good"] for q in qs} == {"Yes", "No"}
    by = rs.questions_by_id()
    assert (by[HIGH_YES]["severity"], by[HIGH_YES]["good"]) == ("High", "Yes")
    assert (by[MEDIUM_NO]["severity"], by[MEDIUM_NO]["good"]) == ("Medium", "No")
    assert (by[CRITICAL_NO]["severity"], by[CRITICAL_NO]["good"]) == ("Critical", "No")
    assert by[VENDOR]["type"] == "vendor" and by[VENDOR]["preferred"]


def test_credit_the_good_answer_earns_all_partial_half_the_bad_answer_and_unknown_none_and_na_does_not_count():
    s = rs.merge_settings(None)
    q = rs.questions_by_id()
    assert rs.credit(q[HIGH_YES], "Yes", s, "m365") == 1.0
    assert rs.credit(q[HIGH_YES], "No", s, "m365") == 0.0
    assert rs.credit(q[MEDIUM_NO], "No", s, "m365") == 1.0, "where Yes is the risk, No is the good answer"
    assert rs.credit(q[MEDIUM_NO], "Yes", s, "m365") == 0.0
    assert rs.credit(q[HIGH_YES], "Partial", s, "m365") == 0.5
    assert rs.credit(q[HIGH_YES], "Unknown", s, "m365") == 0.0, "a control nobody verified is not an assured control"
    assert rs.credit(q[HIGH_YES], "N/A", s, "m365") is None and rs.credit(q[HIGH_YES], None, s, "m365") is None
    assert [rs.credit(q[VENDOR], a, s, "m365") for a in ("Preferred", "Alternative", "None", "Unknown", "N/A")] == [
        1.0,
        1.0,
        0.0,
        0.0,
        None,
    ]


def test_a_failed_high_item_moves_a_category_twice_as_much_as_a_failed_medium_one():
    # Network & Infrastructure: Medium answered right (3 of 3) and one more High... use Administrative for the High: ADM-001 High right (6), ADM-002 Medium wrong (0 of 3) -> 6/9.
    card = rs.scorecard({"ADM-001": "Yes", "ADM-002": "No"})
    adm = category(card, "Administrative")
    assert (adm["points_earned"], adm["points_possible"], adm["answered"], adm["questions"]) == (6, 9, 2, 6)
    assert adm["score"] == pytest.approx(6 / 9) and adm["rating"] == "red"
    flipped = category(rs.scorecard({"ADM-001": "No", "ADM-002": "Yes"}), "Administrative")
    assert flipped["score"] == pytest.approx(3 / 9), "failing the High item costs twice what failing the Medium one does"


def test_a_failed_or_unknown_critical_item_caps_its_category_at_84_percent_however_many_other_items_pass():
    net = [q["id"] for q in rs.library() if q["category"] == "Network & Infrastructure"]
    by = rs.questions_by_id()
    answers = {i: by[i]["good"] for i in net}
    clean = category(rs.scorecard(answers), "Network & Infrastructure")
    assert clean["score"] == 1.0 and clean["rating"] == "green" and clean["critical_gaps"] == 0
    answers[CRITICAL_NO] = "Yes"  # RDP is exposed
    capped = category(rs.scorecard(answers), "Network & Infrastructure")
    assert capped["critical_gaps"] == 1 and capped["raw"] > 0.84 and capped["score"] == 0.84 and capped["rating"] == "red"
    answers[CRITICAL_NO] = "Unknown"
    assert category(rs.scorecard(answers), "Network & Infrastructure")["score"] == 0.84, "unknown on a critical item caps it too"
    off = category(rs.scorecard(answers, settings={"cap_on": False}), "Network & Infrastructure")
    assert off["score"] == off["raw"] > 0.84, "the cap can be switched off in the settings"
    section = next(s for s in capped["sections"] if s["name"] == "Firewalls")
    assert section["score"] == section["raw"], "a section shows its own points; the cap belongs to the category"


def test_the_overall_score_is_the_category_scores_weighted_and_a_category_with_nothing_answered_drops_out():
    by = rs.questions_by_id()
    adm = {q["id"]: by[q["id"]]["good"] for q in rs.library() if q["category"] == "Administrative"}
    assert rs.scorecard(adm)["overall"] == 1.0, "one category answered: it is the whole score"
    backup = next(q for q in rs.library() if q["category"] == "Backup & Disaster Recovery" and q["severity"] != "Critical")
    answers = {**adm, backup["id"]: "Yes" if backup["good"] == "No" else "No"}
    card = rs.scorecard(answers)
    # Administrative 100% at weight 8, Backup 0% at weight 20 -> 8 / 28.
    assert card["overall"] == pytest.approx(8 / 28) and card["rating"] == "red"
    assert rs.scorecard({})["overall"] is None and rs.scorecard({})["rating"] == "na"
    heavier = rs.scorecard(answers, settings={"weights": {"Administrative": 20}})
    assert heavier["overall"] == pytest.approx(20 / 40)


def test_a_microsoft_365_client_is_not_asked_or_scored_on_google_workspace_and_the_other_way_round():
    google = next(q for q in rs.library() if q["category"] == "Google Workspace")
    card = rs.scorecard({google["id"]: "No" if google["good"] == "Yes" else "Yes"}, platform="m365")
    assert category(card, "Google Workspace")["excluded"] is True and category(card, "Google Workspace")["score"] is None
    assert card["total"] == 330 - 76 and card["gap_count"] == 0 and card["overall"] is None
    both = rs.scorecard({google["id"]: "No" if google["good"] == "Yes" else "Yes"}, platform="both")
    assert both["total"] == 330 and both["gap_count"] == 1 and category(both, "Google Workspace")["excluded"] is False
    assert rs.scorecard({}, platform="google")["total"] == 330 - 128


def test_the_gaps_are_the_answered_items_losing_the_most_points_worst_first_at_most_25():
    card = rs.scorecard({HIGH_YES: "Partial", MEDIUM_NO: "Yes", CRITICAL_NO: "Yes", VENDOR: "None", "ADM-002": "Yes"})
    assert [(g["id"], g["severity"], g["points_lost"]) for g in card["gaps"]] == [
        (CRITICAL_NO, "Critical", 10),
        (HIGH_YES, "High", 3),
        (MEDIUM_NO, "Medium", 3),
        (VENDOR, "Medium", 3),
    ], "equal points lost: the more severe item first, then the workbook's order"
    assert card["gap_count"] == 4
    by = rs.questions_by_id()
    everything_wrong = {q["id"]: ("No" if q["good"] == "Yes" else "Yes") if q["type"] == "yesno" else "None" for q in rs.library()}
    wrong = rs.scorecard(everything_wrong, platform="both")
    assert len(wrong["gaps"]) == 25 and wrong["gap_count"] == 330 and wrong["overall"] == 0.0
    assert all(by[g["id"]]["severity"] == "Critical" for g in wrong["gaps"])


def test_changing_a_questions_severity_changes_its_weight_and_the_counts_say_what_is_open_unknown_or_non_standard():
    card = rs.scorecard({HIGH_YES: "No", "ADM-002": "Yes"}, severity_overrides={HIGH_YES: "Low", "ADM-002": "nonsense"})
    adm = category(card, "Administrative")
    assert (adm["points_earned"], adm["points_possible"]) == (3, 4), "the High item now weighs 1; a severity that is not one is ignored"
    counts = rs.scorecard({HIGH_YES: "Unknown", VENDOR: "Alternative", "ADM-002": "N/A"})
    assert (counts["answered"], counts["unknown"], counts["alternative_vendors"], counts["open"]) == (3, 1, 1, 330 - 76 - 3)


def test_the_nist_csf_reading_groups_the_same_answers_by_function_and_respond_has_no_questions():
    card = rs.scorecard({HIGH_YES: "Yes", CRITICAL_NO: "Yes"})
    csf = {f["name"]: f for f in card["csf"]}
    assert list(csf) == list(rs.CSF_ORDER)
    assert csf["Govern"]["score"] == 1.0 and csf["Protect"]["score"] == 0.0
    assert csf["Respond"]["questions"] == 0 and csf["Respond"]["score"] is None and csf["Respond"]["rating"] == "na"


def test_settings_keep_the_defaults_for_anything_missing_out_of_range_or_of_the_wrong_kind():
    s = rs.merge_settings(
        {
            "points": {"Critical": 20, "High": -1, "Low": "x"},
            "partial": 0.25,
            "cap": 7,
            "cap_on": "no",
            "green": 0.9,
            "weights": {"Servers": 0, "Nope": 5},
            "junk": 1,
        }
    )
    assert s["points"] == {"Critical": 20.0, "High": 6, "Medium": 3, "Low": 1}
    assert (s["partial"], s["cap"], s["cap_on"], s["green"]) == (0.25, 0.84, True, 0.9)
    assert s["weights"]["Servers"] == 0.0 and "Nope" not in s["weights"] and "junk" not in s
    assert rs.merge_settings("not a dict") == rs.DEFAULTS
    assert rs.rating(0.95, s) == "green" and rs.rating(0.9, rs.DEFAULTS) == "amber" and rs.rating(0.8499, rs.DEFAULTS) == "red"


def test_a_change_is_in_percentage_points_and_under_half_a_point_is_flat():
    assert rs.points_change(0.82, 0.90) == 8.0 and rs.points_change(0.9, 0.82) == -8.0
    assert rs.points_change(None, 0.9) is None and rs.points_change(0.9, None) is None
    assert [rs.direction(c) for c in (8.0, 0.5, 0.4, 0.0, -0.4, -0.5, None)] == ["up", "up", "flat", "flat", "flat", "down", "none"]


def test_each_assessment_is_compared_with_the_last_one_that_had_a_score_oldest_first():
    points = rs.trend_points(
        [
            {
                "id": "c",
                "review_date": "2026-09-01",
                "score": 0.6,
                "rating": "red",
                "answered": 9,
                "categories": {"Administrative": 1.0, "Servers": 0.5},
            },
            {
                "id": "a",
                "review_date": "2026-03-01",
                "score": 0.8,
                "rating": "red",
                "answered": 5,
                "categories": {"Administrative": 0.5, "Servers": 0.9, "Workstations": 1.0},
            },
            {"id": "b", "review_date": "2026-06-01", "score": None, "rating": "na", "answered": 0, "categories": {}},
        ]
    )
    assert [(p["id"], p["change"], p["direction"], p["compared_with"]) for p in points] == [
        ("a", None, "none", None),
        ("b", None, "none", None),
        ("c", -20.0, "down", "2026-03-01"),
    ]
    changes = rs.category_changes(points)
    assert [(c["name"], c["change"], c["direction"]) for c in changes] == [
        ("Servers", -40.0, "down"),
        ("Administrative", 50.0, "up"),
    ], "a category only one of the two scored is left out"
    assert rs.category_changes(points[:2]) == [] and rs.trend_points([]) == []
