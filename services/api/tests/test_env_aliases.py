"""ACORN_X settings reach the code that reads AISOC_X, the new name wins, and a blank one does not hide the old."""

from app.core.env_aliases import apply_acorn_aliases


def test_new_name_fills_the_old_one_and_wins_over_it():
    env = {"ACORN_CREDENTIAL_KEY": "new", "AISOC_ENVIRONMENT": "production", "ACORN_ENVIRONMENT": "staging"}
    clashes = apply_acorn_aliases(env)
    assert env["AISOC_CREDENTIAL_KEY"] == "new"
    assert env["AISOC_ENVIRONMENT"] == "staging"
    assert clashes == ["ENVIRONMENT"]


def test_blank_new_value_leaves_the_old_one_and_same_values_are_no_clash():
    env = {"ACORN_X": "  ", "AISOC_X": "old", "ACORN_Y": "same", "AISOC_Y": "same", "OTHER": "1"}
    assert apply_acorn_aliases(env) == []
    assert env["AISOC_X"] == "old" and env["AISOC_Y"] == "same" and "AISOC_OTHER" not in env


def test_only_the_acorn_prefix_is_touched_and_nothing_is_removed():
    env = {"ACORN_": "x", "ACORNX": "y", "A_ACORN_Z": "z"}
    apply_acorn_aliases(env)
    assert env == {"ACORN_": "x", "ACORNX": "y", "A_ACORN_Z": "z"}
