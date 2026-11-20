"""The Staff pages of Metrics: Staff Metrics, Pods, Ticket Updates, DialPad, Staff Hours Distribution and the Scorecard (with the scoring rules Rewst's template used). Numbers worked out by hand."""

import pytest
from app.services import metrics_staff as ms

W1, W2 = "2026-10-26", "2026-11-02"


def row(week, who, team, **over):
    base = {
        "week": week,
        "agent_id": who,
        "engineer": who,
        "team": team,
        "labor_hours": 0,
        "weekly_utilization": 0,
        "days_off": 0,
        "holidays": 0,
        "days_worked": 5,
        "closed": 0,
        "ticket_updates": 0,
        "comments_added": 0,
        "created": 0,
        "total_calls": 0,
        "total_call_time": 0,
    }
    return base | over


STAFF = {
    "weeks": [W1, W2],
    "rows": [
        row(
            W1,
            "Dan",
            "Pod 1",
            labor_hours=30,
            weekly_utilization=70,
            closed=31,
            ticket_updates=20,
            created=5,
            total_calls=10,
            total_call_time=300,
            surveys={"total_surveys": 2, "survey_sum": 9},
        ),
        row(
            W2,
            "Dan",
            "Pod 1",
            labor_hours=12,
            weekly_utilization=40,
            days_off=2,
            days_worked=3,
            closed=9,
            ticket_updates=12,
            created=2,
            total_calls=2,
            total_call_time=30,
        ),
        row(W1, "Vic", "Pod 2", labor_hours=5, weekly_utilization=20, closed=1),
        row(W2, "Vic", "Pod 2"),
    ],
}


def test_a_period_is_the_newest_weeks_and_a_year_is_fifty_two_at_most():
    many = {"rows": [{"week": f"2025-{m:02d}-{d:02d}"} for m in range(1, 13) for d in (1, 8, 15, 22)]}
    assert len(ms.recent_weeks(many, 3)) == 13 and len(ms.recent_weeks(many, 1)) == 4 and len(ms.recent_weeks(many, 12)) == 48
    assert ms.recent_weeks(STAFF, 1) == [W1, W2] and ms.recent_weeks(None, 3) == []


def test_staff_metrics_utilization_is_logged_hours_over_available_hours_the_way_rewst_counts_it_and_filters_by_team():
    r = ms.staff_metrics(STAFF, 1)
    # a team's week is all its logged hours over all its available hours (40 each, less time off in hours): (30 + 5) / 80 and 12 / (38 + 40)
    assert [(w["week"], w["utilization"], w["closed"]) for w in r["weeks"]] == [(W1, 43.8, 32), (W2, 15.4, 9)]
    assert [(m["engineer"], m["utilization"], m["closed"], m["labor_hours"]) for m in r["members"]] == [("Dan", 53.8, 40, 42.0), ("Vic", 6.2, 1, 5.0)]
    assert r["members"][0]["by_week"] == {W1: 75.0, W2: 31.58}, "30 / 40 and 12 / 38"
    assert r["teams"] == ["Pod 1", "Pod 2"]
    only = ms.staff_metrics(STAFF, 1, "Pod 2")
    assert [m["engineer"] for m in only["members"]] == ["Vic"] and only["weeks"][0]["utilization"] == 12.5
    assert ms.week_util({"labor_hours": 5, "days_off": 40}) is None, "nothing available is no utilization, not a divide by zero"


def test_pods_group_the_engineers_by_team_with_days_off_and_a_week_by_week_list():
    r = ms.pods(STAFF, 1)
    one, two = r["pods"]
    assert (one["pod"], one["engineers"], one["utilization"], one["resolved"], one["created"], one["days_off"]) == (
        "Pod 1",
        1,
        55.0,
        40,
        7,
        2.0,
    )
    assert (two["pod"], two["utilization"], two["resolved"]) == ("Pod 2", 20.0, 1)
    assert [w["week"] for w in one["weekly"]] == [W1, W2] and one["weekly"][1]["engineers"][0]["days_off"] == 2.0


def test_ticket_updates_are_a_member_by_week_table_for_the_members_chosen():
    r = ms.ticket_updates(STAFF, 1)
    assert [(x["engineer"], x["total"], x["by_week"]) for x in r["rows"]] == [("Dan", 32, {W1: 20, W2: 12}), ("Vic", 0, {W1: 0, W2: 0})]
    assert r["weekly_total"] == {W1: 20, W2: 12} and r["members"] == ["Dan", "Vic"]
    assert [x["engineer"] for x in ms.ticket_updates(STAFF, 1, ["Vic"])["rows"]] == ["Vic"]


DIALPAD = {
    "rows": [
        {"week": W1, "engineer": "Dan", "total_calls": 10, "total_call_time": 300, "triage_inbound": 4},
        {"week": W2, "engineer": "Dan", "total_calls": 2, "total_call_time": 30, "triage_inbound": 1},
        {"week": W1, "engineer": "Vic", "total_calls": 3, "total_call_time": 60, "triage_inbound": 2},
    ]
}


def test_dialpad_gives_triage_and_hours_on_call_by_week_and_calls_per_person():
    r = ms.dialpad(DIALPAD, 1)
    assert [(w["week"], w["triage_inbound"], w["hours_on_call"], w["calls"]) for w in r["weeks"]] == [(W1, 6, 6.0, 13), (W2, 1, 0.5, 2)]
    assert [(p["engineer"], p["calls"], p["hours"]) for p in r["people"]] == [("Dan", 12, 5.5), ("Vic", 3, 1.0)]
    only = ms.dialpad(DIALPAD, 1, "Vic")
    assert [p["engineer"] for p in only["people"]] == ["Vic"] and only["engineers"] == ["Dan", "Vic"]


PROFIT = {
    "months": ["2026-09", "2026-10"],
    "hours": [
        {"client": "Acme", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 4},
        {"client": "Acme", "month": "2026-10", "agent_id": "41", "charge_type": "vCIO", "hours": 2.5},
        {"client": "Birch", "month": "2026-10", "agent_id": "40", "charge_type": "Remote Support", "hours": 1},
        {"client": "Nobody", "month": "2026-10", "agent_id": "40", "charge_type": "No Charge", "hours": 3},
        {"client": "Acme", "month": "2026-09", "agent_id": "40", "charge_type": "Remote Support", "hours": 10},
    ],
    "agents": [{"id": "40", "name": "Dan Kemp"}, {"id": "41", "name": "Vic Cio"}],
}


def test_staff_hours_distribution_splits_each_persons_hours_by_ticket_type():
    r = ms.hours_distribution(PROFIT, 2)
    assert r["total_hours"] == 20.5
    assert [(t["type"], t["hours"], t["share_percent"]) for t in r["types"]] == [
        ("Remote Support", 15.0, 73.2),
        ("No Charge", 3.0, 14.6),
        ("vCIO", 2.5, 12.2),
    ]
    assert [(p["name"], p["total"], p["by_type"]) for p in r["people"]] == [
        ("Dan Kemp", 18.0, {"Remote Support": 15.0, "No Charge": 3.0, "vCIO": 0.0}),
        ("Vic Cio", 2.5, {"Remote Support": 0.0, "No Charge": 0.0, "vCIO": 2.5}),
    ]
    assert ms.hours_distribution(PROFIT, 1)["total_hours"] == 10.5 and ms.hours_distribution(None, 3)["people"] == []


def test_each_metric_is_scored_from_the_bracket_row_for_the_days_worked():
    full = row(
        W1,
        "Dan",
        "Pod 1",
        closed=31,
        ticket_updates=20,
        labor_hours=30,
        total_calls=10,
        total_call_time=300,
        weekly_utilization=70,
        surveys={"total_surveys": 2, "survey_sum": 9},
    )
    assert [ms.metric_score(m, full) for m in ms.METRIC_ORDER] == [5, 3, 5, 3, 5, 4, 4]
    three = row(
        W2,
        "Dan",
        "Pod 1",
        closed=9,
        ticket_updates=12,
        labor_hours=12,
        total_calls=2,
        total_call_time=30,
        weekly_utilization=40,
        days_worked=3,
    )
    assert [ms.metric_score(m, three) for m in ms.METRIC_ORDER] == [2, 3, 4, 2, 1, None, 2]


def test_a_metric_below_every_bracket_gets_its_floor_and_call_time_is_scored_in_hours_not_minutes():
    low = row(W1, "Vic", "Pod 2", closed=0, labor_hours=0.5, total_call_time=0)
    assert (
        ms.metric_score("Tickets Closed", low) == 0 and ms.metric_score("Labor Hours", low) == 1 and ms.metric_score("Call Time", low) == 1
    )
    assert ms.metric_score("Call Time", row(W1, "x", "p", total_call_time=299)) == 4, "299 minutes is 4.98 hours, not 5"
    assert ms.metric_score("Call Time", row(W1, "x", "p", total_call_time=300)) == 5


def test_a_week_score_is_the_weighted_average_without_the_metrics_that_have_nothing_to_score():
    assert ms.week_score(STAFF["rows"][0]) == 4.3, "(15 + 4.5 + 10 + 1.5 + 2.5 + 4 + 10) / 11"
    assert ms.week_score(STAFF["rows"][1]) == 2.5, "no survey, so CSAT leaves the weighting: 25 / 10"
    assert ms.week_score(STAFF["rows"][2]) == 1.0


def test_a_week_with_no_activity_or_all_of_it_off_is_not_scored_instead_of_scored_zero():
    assert ms.week_score(STAFF["rows"][3]) is None
    assert ms.week_score(row(W1, "x", "p", labor_hours=40, closed=40, days_worked=0)) is None
    assert (
        ms.day_bucket({}) == 5
        and ms.day_bucket({"days_worked": 4.5}) == 4
        and ms.day_bucket({"days_worked": 9}) == 5
        and ms.day_bucket({"days_worked": -1}) == 0
    )


@pytest.mark.parametrize(
    "avg,letter", [(5, "S"), (4.5, "S"), (4.49, "A"), (4.0, "A"), (3.99, "B"), (3.0, "B"), (2.0, "C"), (1.0, "D"), (0.5, "F"), (None, "-")]
)
def test_grades(avg, letter):
    assert ms.grade(avg) == letter


def test_the_scorecard_ranks_people_by_average_and_details_one_week_by_week():
    r = ms.scorecard(STAFF, 1, "Dan")
    assert [(p["engineer"], p["average"], p["grade"], p["weeks_scored"]) for p in r["people"]] == [
        ("Dan", 3.4, "B", 2),
        ("Vic", 1.0, "D", 1),
    ]
    d = r["detail"]
    assert (d["engineer"], d["average"], d["grade"]) == ("Dan", 3.4, "B")
    assert [(w["week"], w["score"], w["grade"]) for w in d["weeks"]] == [(W2, 2.5, "C"), (W1, 4.3, "A")], "newest week first"
    assert [t["score"] for t in d["trend"]] == [4.3, 2.5], "the trend runs oldest to newest"
    assert d["metric_averages"]["Tickets Closed"] == 3.5 and d["metric_averages"]["CSAT"] == 4.0
    assert r["weights"]["Utilization"] == 2.5 and r["metrics"][0] == "Tickets Closed"


def test_an_unscored_week_still_shows_in_the_detail_with_no_scores():
    d = ms.scorecard(STAFF, 1, "Vic")["detail"]
    skipped = next(w for w in d["weeks"] if w["week"] == W2)
    assert skipped["score"] is None and skipped["grade"] == "-" and set(skipped["factors"].values()) == {None}
    assert d["average"] == 1.0
    assert ms.scorecard(STAFF, 1, "Nobody")["detail"] is None


def test_a_metric_that_is_not_reported_at_all_leaves_the_weighting_instead_of_scoring_zero():
    # Dialpad is not connected: the week carries no call fields, so Calls Made and Call Time are not scored; it is the other five metrics that count
    no_calls = {
        k: v
        for k, v in row(
            W1,
            "Dan",
            "Pod 1",
            closed=31,
            ticket_updates=20,
            labor_hours=30,
            weekly_utilization=70,
            surveys={"total_surveys": 2, "survey_sum": 9},
        ).items()
        if not k.startswith("total_call")
    }
    assert ms.metric_score("Calls Made", no_calls) is None and ms.metric_score("Call Time", no_calls) is None
    assert ms.week_score(no_calls) == 4.4, "(15 + 4.5 + 10 + 4 + 10) / 10: the call metrics are not in the weighting"
    zero_calls = row(
        W1,
        "Dan",
        "Pod 1",
        closed=31,
        ticket_updates=20,
        labor_hours=30,
        weekly_utilization=70,
        surveys={"total_surveys": 2, "survey_sum": 9},
    )
    assert ms.metric_score("Calls Made", zero_calls) == 0, "a reported zero is still a zero"


def test_merging_a_dataset_keeps_older_rows_replaces_the_same_row_and_caps_the_history():
    from app.models.metric_dataset import merge_dataset

    held = {"weeks": ["a", "b"], "rows": [{"week": "a", "agent_id": "1", "v": 1}, {"week": "b", "agent_id": "1", "v": 2}]}
    new = {"rows": [{"week": "b", "agent_id": "1", "v": 9}, {"week": "c", "agent_id": "1", "v": 3}]}
    out = merge_dataset("staff-weekly", held, new)
    assert [(r["week"], r["v"]) for r in out["rows"]] == [("a", 1), ("b", 9), ("c", 3)] and out["weeks"] == ["a", "b", "c"]
    assert merge_dataset("ticket-detail", held, new) == new and merge_dataset("staff-weekly", None, new) == new
    roles = merge_dataset(
        "m365-roles",
        {"clients": [{"client_id": "1", "client_name": "A"}, {"client_id": "2", "client_name": "B"}]},
        {"clients": [{"client_id": "2", "client_name": "B2"}]},
    )
    assert sorted((c["client_id"], c["client_name"]) for c in roles["clients"]) == [("1", "A"), ("2", "B2")]


def test_a_merged_row_sent_again_keeps_a_field_the_new_row_leaves_out():
    from app.models.metric_dataset import merge_dataset

    held = {"rows": [{"week": "a", "agent_id": "1", "closed": 4, "ticket_updates": 17}]}
    out = merge_dataset("staff-weekly", held, {"rows": [{"week": "a", "agent_id": "1", "closed": 5}]})
    assert out["rows"] == [
        {"week": "a", "agent_id": "1", "closed": 5, "ticket_updates": 17}
    ], "the new closed count wins; the updates CORE did not read this time stay"


def test_pods_give_one_row_per_engineer_per_week_for_the_matrix_with_clean_names_and_logged_hours():
    rows = [row(W2, "Al  Ex", "Pod 1", labor_hours=30.456, closed=3, created=4, days_off=8, holidays=0)]
    out = ms.pods({"weeks": [W2], "rows": rows}, 1)["rows"]
    assert out == [{"week": W2, "pod": "Pod 1", "engineer": "Al Ex", "resolved": 3, "created": 4, "logged_hours": 30.46, "days_off": 8.0, "holidays": 0.0}]


def test_the_scoring_template_shows_every_weight_bracket_and_grade_the_scorecard_really_uses():
    t = ms.scoring_template()
    assert [m["metric"] for m in t["metrics"]] == list(ms.METRIC_ORDER)
    assert t["total_weight"] == sum(c["weight"] for c in ms.METRIC_CONFIG.values()) == 11.0
    assert round(sum(m["share"] for m in t["metrics"]), 0) == 100
    closed = t["metrics"][0]
    assert closed["by_days_worked"] and list(closed["tables"]) == ["5", "4", "3", "2", "1"] and closed["tables"]["5"][0] == [30.0, 5]
    csat = [m for m in t["metrics"] if m["metric"] == "CSAT"][0]
    assert not csat["by_days_worked"] and csat["tables"]["any"] == [[5.0, 5], [4.0, 4], [3.0, 3], [2.0, 2], [1.0, 1]]
    # the grades shown are the grades given
    for g in t["grades"]:
        assert ms.grade(g["from"] if g["from"] > 0 else 0.5) == g["grade"] or g["grade"] == "F"
    assert [g["grade"] for g in t["grades"]] == ["S", "A", "B", "C", "D", "F"]
    # a week at exactly each bracket edge earns the score the page shows
    for m in t["metrics"]:
        if m["by_days_worked"]:
            for threshold, score in m["tables"]["5"]:
                scale = ms.METRIC_CONFIG[m["metric"]].get("scale", 1)
                row = {ms.METRIC_CONFIG[m["metric"]]["field"]: threshold / scale, "days_worked": 5}
                assert ms.metric_score(m["metric"], row) == score


def test_ticket_updates_also_give_comments_updates_and_resolved_per_person_per_week():
    rows = [row(W1, "Dan", "Pod 1", ticket_updates=20, comments_added=7, closed=31), row(W2, "Dan", "Pod 1", ticket_updates=2, closed=1)]
    r = ms.ticket_updates({"weeks": [W1, W2], "rows": rows}, 1)
    assert r["rows"][0]["detail"] == {W1: {"comments": 7, "updated": 20, "resolved": 31}, W2: {"comments": 0, "updated": 2, "resolved": 1}}
    assert r["rows"][0]["by_week"] == {W1: 20, W2: 2}


MEET = {
    "weeks": [W1, W2],
    "rows": [
        {"week": W1, "engineer": "Ann", "team": "Pod 1", "total_hours": 3.5},
        {"week": W2, "engineer": "Ann", "team": "Pod 1", "total_hours": 2},
        {"week": W2, "engineer": "Bob", "team": "", "total_hours": "1.25"},
        {"week": W2, "engineer": "Neg", "team": "Pod 1", "total_hours": -4},
    ],
}


def test_meetings_total_by_week_by_person_and_by_team_with_no_team_as_unassigned_and_a_team_filter():
    r = ms.meetings(MEET, 1)
    assert r["total_hours"] == 6.75 and r["by_week"] == [{"week": W1, "hours": 3.5}, {"week": W2, "hours": 3.25}]
    assert [(p["engineer"], p["total"], p["by_week"]) for p in r["people"]] == [("Ann", 5.5, {W1: 3.5, W2: 2.0}), ("Bob", 1.25, {W2: 1.25}), ("Neg", 0.0, {W2: 0.0})], "a negative figure counts as nothing"
    assert r["by_team"] == [{"team": "Pod 1", "hours": 5.5}, {"team": "Unassigned", "hours": 1.25}] and r["teams"] == ["Pod 1", "Unassigned"]
    only = ms.meetings(MEET, 1, "Unassigned")
    assert [p["engineer"] for p in only["people"]] == ["Bob"] and only["total_hours"] == 1.25
    assert ms.meetings(None, 3)["people"] == []


def test_halo_user_roles_count_users_per_client_and_role_with_totals_a_client_filter_and_what_could_not_be_read():
    data = {
        "roles": ["Primary POC", "Computer User"],
        "clients": [
            {"client": "Birch", "client_id": "6", "counts": {"Computer User": 1}},
            {"client": "Acme", "client_id": "5", "counts": {"Primary POC": 1, "Computer User": 2, "Gone": 9}},
        ],
        "without_client": 1,
        "unread": ["Contractor"],
    }
    r = ms.halo_user_roles(data)
    assert r["roles"] == [{"role": "Computer User", "total": 3}, {"role": "Primary POC", "total": 1}]
    assert [(c["client"], c["total"], c["counts"]) for c in r["clients"]] == [("Acme", 3, {"Computer User": 2, "Primary POC": 1}), ("Birch", 1, {"Computer User": 1, "Primary POC": 0})], "a role no longer listed is not counted"
    assert r["all_clients"] == ["Acme", "Birch"] and r["without_client"] == 1 and r["unread"] == ["Contractor"]
    assert [c["client"] for c in ms.halo_user_roles(data, ["Birch"])["clients"]] == ["Birch"]
    assert ms.halo_user_roles(None)["clients"] == []
