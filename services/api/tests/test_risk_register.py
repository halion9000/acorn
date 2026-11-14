"""The risk register's pure rules: the score and its words, the grid, the library and the history lines."""

from types import SimpleNamespace

from app.services import risk_register as rr


def test_the_score_is_likelihood_times_impact_and_its_level_has_four_bands():
    assert rr.score(3, 4) == 12
    assert rr.score(None, 4) is None
    assert [rr.level(v) for v in (1, 4, 5, 9, 10, 15, 16, 25, None)] == [
        "low",
        "low",
        "medium",
        "medium",
        "high",
        "high",
        "critical",
        "critical",
        None,
    ]


def test_the_grid_puts_likelihood_5_on_the_top_row_and_impact_1_in_the_first_column():
    rows = [SimpleNamespace(likelihood=5, impact=1), SimpleNamespace(likelihood=5, impact=1), SimpleNamespace(likelihood=1, impact=5)]
    grid = rr.matrix(rows)
    assert grid[0][0] == 2 and grid[4][4] == 1
    assert sum(sum(r) for r in grid) == 3


def test_every_library_risk_is_complete_and_unique_and_in_a_known_category():
    ids = [i["id"] for i in rr.LIBRARY]
    assert len(ids) == len(set(ids)) >= 12
    titles = [i["title"] for i in rr.LIBRARY]
    assert len(titles) == len(set(titles))
    for i in rr.LIBRARY:
        assert i["category"] in rr.CATEGORIES
        assert 1 <= i["likelihood"] <= 5 and 1 <= i["impact"] <= 5
        assert i["description"]
    assert rr.library_item("ransomware")["title"].startswith("Ransomware")
    assert rr.library_item("nope") is None


def test_the_history_says_what_changed_in_words_and_says_nothing_when_nothing_did():
    before = {
        "title": "A",
        "description": "x",
        "category": "Other",
        "owner": None,
        "likelihood": 3,
        "impact": 4,
        "treatment": "undecided",
        "treatment_note": "",
        "residual_likelihood": None,
        "residual_impact": None,
    }
    after = {**before, "likelihood": 4, "owner": "Hal", "description": "y", "treatment": "mitigate", "residual_likelihood": 2}
    lines = rr.describe_changes(before, after)
    assert "Likelihood 3 to 4" in lines
    assert "Owner none to Hal" in lines
    assert "Description changed" in lines
    assert "Treatment undecided to mitigate" in lines
    assert "Residual likelihood none to 2" in lines
    assert rr.describe_changes(before, dict(before)) == []
