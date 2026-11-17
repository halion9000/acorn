"""The vendor register's pure rules: month arithmetic, where a vendor's reviews stand, and the history wording."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.services.vendor_management import add_months, describe_changes, review_state


def rev(status="in_progress", due=date(2026, 12, 1), completed=None):
    return SimpleNamespace(status=status, due_date=due, completed_at=completed)


def done_on(d):
    return datetime(d.year, d.month, d.day, 12, tzinfo=UTC)


TODAY = date(2026, 11, 14)


def test_add_months_keeps_the_day_or_clamps_to_the_end_of_a_short_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 14), 12) == date(2027, 11, 14)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_an_open_review_is_in_progress_until_its_due_date_passes_then_overdue():
    assert review_state(None, [rev(due=date(2026, 12, 1))], date(2026, 1, 1), TODAY)["state"] == "in_progress"
    s = review_state(None, [rev(due=date(2026, 11, 1))], date(2026, 1, 1), TODAY)
    assert s["state"] == "overdue" and s["next_due"] == date(2026, 11, 1)


def test_no_schedule_and_no_open_review_is_none():
    assert review_state(None, [], date(2026, 1, 1), TODAY) == {"state": "none", "next_due": None, "last_completed": None}


def test_a_schedule_counts_from_the_last_completed_review_and_turns_due_then_overdue():
    done = [rev("complete", completed=done_on(date(2026, 5, 20)))]
    cur = review_state(12, done, date(2025, 1, 1), TODAY)
    assert (cur["state"], cur["next_due"], cur["last_completed"]) == ("current", date(2027, 5, 20), date(2026, 5, 20))
    assert review_state(6, done, date(2025, 1, 1), TODAY)["state"] == "due"
    assert review_state(3, done, date(2025, 1, 1), TODAY)["state"] == "overdue"


def test_a_scheduled_vendor_never_reviewed_is_due_from_the_day_it_was_added():
    assert review_state(12, [], date(2026, 11, 14), TODAY)["state"] == "due"
    assert review_state(12, [], date(2026, 6, 1), TODAY)["state"] == "overdue"


def test_changes_are_described_one_line_each_without_copying_notes():
    before = {"risk_level": "unassessed", "mfa": None, "notes": "a", "owner": "Hal", "name": "X"}
    after = {"risk_level": "high", "mfa": True, "notes": "b", "owner": None, "name": "X"}
    assert set(describe_changes(before, after)) == {
        "Owner Hal to none",
        "Risk level unassessed to high",
        "Two-factor sign-in none to yes",
        "Notes changed",
    }
    assert describe_changes(before, dict(before)) == []


def test_the_yearly_cost_adds_up_in_total_and_by_category_largest_first_leaving_out_vendors_with_no_amount():
    from app.services.vendor_management import spend_by_category, spend_total

    rows = [("Security", 1200.5), ("Security", 99.5), ("Backup", 5000), ("Backup", None), ("Other", None), ("Email", 5000)]
    assert spend_total(a for _c, a in rows) == 11300.0
    assert spend_by_category(rows) == {"Backup": 5000.0, "Email": 5000.0, "Security": 1300.0}
    assert list(spend_by_category(rows)) == ["Backup", "Email", "Security"], "ties are by name, then smaller sums"
    assert spend_total([]) == 0.0
    assert spend_by_category([]) == {}
    assert spend_total([0.1, 0.2]) == 0.3, "rounded to cents, not 0.30000000000000004"


def test_a_change_of_yearly_cost_reads_as_one_plain_history_line():
    from decimal import Decimal

    from app.services.vendor_management import describe_changes

    assert describe_changes({"annual_spend": None}, {"annual_spend": Decimal("1200.00")}) == ["Yearly cost none to 1200.00"]
    assert describe_changes({"annual_spend": Decimal("1200.00")}, {"annual_spend": Decimal("1200")}) == []
