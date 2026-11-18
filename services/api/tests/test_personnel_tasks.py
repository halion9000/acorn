"""Onboarding and offboarding checklists (pure rules)."""

from datetime import date

from app.services import personnel_tasks as pt

TODAY = date(2026, 11, 18)


def test_a_checklist_starts_with_every_task_of_its_kind_each_with_a_due_day():
    got = pt.tasks_to_start("onboarding", set(), TODAY)
    assert [t for t, _ in got] == [t for t, _ in pt.TEMPLATES["onboarding"]]
    assert got[0] == ("Create the account and assign the licenses", date(2026, 11, 19))
    assert dict(pt.tasks_to_start("offboarding", set(), TODAY))["Disable the account and end its sessions"] == TODAY, "access goes the same day"
    assert pt.tasks_to_start("nonsense", set(), TODAY) == []


def test_starting_again_adds_only_what_is_missing_whatever_the_case_of_the_title():
    have = {"set up multi-factor authentication ", "Complete the security awareness training"}
    titles = [t for t, _ in pt.tasks_to_start("onboarding", have, TODAY)]
    assert "Set up multi-factor authentication" not in titles and "Complete the security awareness training" not in titles
    assert len(titles) == len(pt.TEMPLATES["onboarding"]) - 2
    everything = {t for t, _ in pt.TEMPLATES["offboarding"]}
    assert pt.tasks_to_start("offboarding", everything, TODAY) == []


def test_progress_counts_done_open_and_overdue_for_one_kind_only():
    tasks = [
        pt.Task("onboarding", True, date(2026, 11, 1)),
        pt.Task("onboarding", False, date(2026, 11, 10)),  # open and past its day
        pt.Task("onboarding", False, date(2026, 11, 30)),
        pt.Task("onboarding", False, None),
        pt.Task("offboarding", False, date(2026, 11, 1)),
    ]
    assert pt.progress(tasks, "onboarding", TODAY) == {"started": True, "total": 4, "done": 1, "open": 3, "overdue": 1}
    assert pt.progress(tasks, "offboarding", TODAY) == {"started": True, "total": 1, "done": 0, "open": 1, "overdue": 1}
    assert pt.progress([], "onboarding", TODAY) == {"started": False, "total": 0, "done": 0, "open": 0, "overdue": 0}


def test_every_built_in_task_is_unique_within_its_list_and_none_is_empty():
    for kind, items in pt.TEMPLATES.items():
        titles = [t.lower() for t, _ in items]
        assert len(titles) == len(set(titles)), kind
        assert all(len(t) >= 3 and d >= 0 for t, d in items), kind
