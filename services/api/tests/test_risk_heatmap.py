"""The risk heat map for a date and its movement month by month (pure rules)."""

from datetime import UTC, date, datetime

from app.services import risk_heatmap as hm

D = lambda y, m, d: datetime(y, m, d, 12, tzinfo=UTC)  # noqa: E731


def lv(risk, at, l, i, rl=None, ri=None, active=True):
    return hm.Levels(risk, at, l, i, rl, ri, active)


def cell_of(h, l, i):
    return next(c for c in h["cells"] if c["likelihood"] == l and c["impact"] == i)


def test_the_map_for_a_date_uses_the_newest_row_of_each_risk_on_or_before_it():
    rows = [lv("a", D(2026, 1, 5), 2, 2), lv("a", D(2026, 6, 1), 4, 5), lv("b", D(2026, 3, 1), 3, 3)]
    early = hm.heatmap(rows, D(2026, 2, 1))
    assert early["total"] == 1 and cell_of(early, 2, 2)["risk_ids"] == ["a"], "b did not exist yet and a was still low"
    later = hm.heatmap(rows, D(2026, 7, 1))
    assert later["total"] == 2 and cell_of(later, 4, 5)["risk_ids"] == ["a"] and cell_of(later, 3, 3)["risk_ids"] == ["b"]
    assert later["by_level"] == {"critical": 1, "high": 0, "medium": 1, "low": 0}, "4x5 is critical, 3x3 is medium"
    exact = hm.heatmap(rows, D(2026, 6, 1))
    assert cell_of(exact, 4, 5)["count"] == 1, "a change at that moment counts"


def test_the_grid_has_every_likelihood_and_impact_from_five_down_to_one_and_levels_of_each_cell():
    h = hm.heatmap([], D(2026, 7, 1))
    assert len(h["cells"]) == 25 and h["total"] == 0
    assert [(c["likelihood"], c["impact"]) for c in h["cells"][:6]] == [(5, 1), (5, 2), (5, 3), (5, 4), (5, 5), (4, 1)]
    assert cell_of(h, 5, 5)["level"] == "critical" and cell_of(h, 1, 1)["level"] == "low" and cell_of(h, 2, 5)["level"] == "high" and cell_of(h, 2, 3)["level"] == "medium"


def test_an_archived_risk_stops_counting_from_then_and_counts_again_when_brought_back():
    rows = [lv("a", D(2026, 1, 1), 3, 3), lv("a", D(2026, 4, 1), 3, 3, active=False), lv("a", D(2026, 8, 1), 3, 3)]
    assert hm.heatmap(rows, D(2026, 3, 1))["total"] == 1
    assert hm.heatmap(rows, D(2026, 5, 1))["total"] == 0
    assert hm.heatmap(rows, D(2026, 9, 1))["total"] == 1


def test_the_after_treatment_map_uses_the_residual_levels_and_a_risk_without_them_stays_where_it_started():
    rows = [lv("a", D(2026, 1, 1), 5, 5, 2, 2), lv("b", D(2026, 1, 1), 4, 4)]
    inherent, residual = hm.heatmap(rows, D(2026, 2, 1), "inherent"), hm.heatmap(rows, D(2026, 2, 1), "residual")
    assert cell_of(inherent, 5, 5)["risk_ids"] == ["a"]
    assert cell_of(residual, 2, 2)["risk_ids"] == ["a"] and cell_of(residual, 4, 4)["risk_ids"] == ["b"] and cell_of(residual, 5, 5)["count"] == 0


def test_month_ends_are_the_last_days_of_the_twelve_months_before_this_one_then_today():
    ends = hm.month_ends(date(2026, 11, 18), 12)
    assert ends[0] == date(2025, 11, 30) and ends[-2] == date(2026, 10, 31) and ends[-1] == date(2026, 11, 18) and len(ends) == 13
    assert hm.month_ends(date(2026, 1, 10), 2) == [date(2025, 11, 30), date(2025, 12, 31), date(2026, 1, 10)]
    assert hm.month_ends(date(2024, 3, 5), 1)[0] == date(2024, 2, 29), "a leap year"


def test_the_monthly_trend_counts_the_risks_at_each_level_at_each_month_end():
    rows = [lv("a", D(2026, 8, 10), 5, 5), lv("a", D(2026, 10, 20), 2, 2), lv("b", D(2026, 9, 3), 3, 4)]
    trend = hm.monthly(rows, date(2026, 11, 18), "inherent", 4)
    by = {t["date"]: t for t in trend}
    assert by["2026-07-31"]["total"] == 0
    assert (by["2026-08-31"]["total"], by["2026-08-31"]["critical"]) == (1, 1)
    assert (by["2026-09-30"]["total"], by["2026-09-30"]["critical"], by["2026-09-30"]["high"]) == (2, 1, 1)
    assert (by["2026-10-31"]["critical"], by["2026-10-31"]["low"], by["2026-10-31"]["high"]) == (0, 1, 1), "a came down on 20 October"
    assert trend[-1]["date"] == "2026-11-18"
