"""Who has accepted a policy's newest version: accepted, pending (with the older version they did accept), and people who accepted but are no longer listed."""

from datetime import date

from app.services.policy_acceptance import Accepted, norm, summarize

D = date(2026, 11, 1)


def acc(email, version, name=None):
    return Accepted(email, name, version, D, "hal@x")


def test_split_by_the_newest_version_and_older_acceptance_still_counts_as_pending():
    people = [("Ann@x.com", "Ann"), ("bob@x.com", "Bob"), ("cy@x.com", None)]
    rows = [acc("ann@x.com", 2), acc("BOB@x.com", 1), acc("old@x.com", 2)]
    out = summarize(people, rows, 2)
    assert [a.email for a in out["accepted"]] == ["ann@x.com"]
    assert out["pending"] == [
        {"email": "bob@x.com", "name": "Bob", "older_version": 1},
        {"email": "cy@x.com", "name": None, "older_version": None},
    ]
    assert [a.email for a in out["others"]] == ["old@x.com"]
    assert out["share"] == 0.333


def test_nobody_listed_means_no_share_and_the_latest_older_version_is_reported():
    assert summarize([], [], 1)["share"] is None
    out = summarize([("a@x.com", None)], [acc("a@x.com", 1), acc("a@x.com", 2)], 3)
    assert out["pending"][0]["older_version"] == 2


def test_norm_trims_and_lowercases():
    assert norm("  A@X.com ") == "a@x.com"
