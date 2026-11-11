"""The alert a finished BEC search raises: only from CIPP's own High or Medium rating, worded from what the report actually holds, and never calling a quiet search clean."""

from datetime import UTC, datetime

from app.services import bec_findings as bf

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def make(level="High", score=9, incomplete=(), report=None, **over):
    summary = {"level": level, "score": score, "incomplete": list(incomplete), "guid": "g1"}
    summary = {k: v for k, v in summary.items() if v is not None and not (k == "level" and level is None)}
    args = {"case_ref": "BEC-1", "case_id": "case-1", "email": "pat@acme.com", "summary": summary, "report": report, "now": NOW}
    args.update(over)
    return bf.finding_for_case(**args)


def test_a_high_level_is_a_high_alert_for_that_person_with_cipps_own_words():
    f = make("High", 9, report={"NewRules": [{"Name": "x"}, {"Name": "y"}], "MailboxPermissionChanges": [{}], "AddedApps": []})
    assert (f.severity, f.rule_id, f.key, f.users) == ("high", "aisoc-id-bec-findings", "case-1", ["pat@acme.com"])
    assert "CIPP rates it High" in f.title and "pat@acme.com" in f.title
    fields = dict(f.fields)
    assert fields["CIPP's level"] == "High" and fields["CIPP's score"] == "9" and fields["Search"] == "BEC-1"
    assert (
        fields["Seen in the report"] == "2 new inbox rules; 1 mailbox permission change"
    ), "only lists with entries, counted from the report itself"


def test_medium_is_a_medium_alert_and_low_or_missing_or_unknown_raises_nothing():
    assert make("Medium", 5).severity == "medium"
    assert make("medium", 5).severity == "medium", "the level is read without regard to case"
    for level in ("Low", "", None, "Critical", "none"):
        assert make(level, 1) is None, level


def test_collectors_that_could_not_finish_are_named_and_the_wording_says_the_picture_may_be_incomplete():
    f = make("High", 8, incomplete=["SignIns", "MobileDevices"])
    assert dict(f.fields)["Checks that could not finish"] == "SignIns, MobileDevices"
    assert "may be incomplete" in f.summary
    assert "may be incomplete" not in make("High", 8).summary


def test_a_rating_with_no_signal_lists_says_so_instead_of_inventing_findings():
    f = make("High", 8, report={"NewRules": [], "Completeness": {}})
    assert "other signals" in dict(f.fields)["Seen in the report"]
    assert "other signals" in make("High", 8, report=None).fields[3][1]


def test_a_section_that_is_not_a_list_is_not_counted():
    assert bf.signal_counts({"NewRules": {"Name": "x"}, "AddedApps": "none", "NewUsers": [1, 2, 3]}) == [("new user", 3)]


def test_the_same_search_always_gives_the_same_alert_id_so_a_repeat_makes_one():
    import uuid

    from app.services.identity_detections import alert_id

    t = uuid.uuid4()
    assert alert_id(t, make("High")) == alert_id(t, make("High", 10)), "the key is the case, not the score"
    assert alert_id(t, make("High")) != alert_id(t, make("High", case_id="case-2"))


def test_the_summary_never_says_clean_or_compromised_as_a_fact():
    f = make("High", 9)
    text = (f.title + " " + f.summary).lower()
    for phrase in ("is clean", "are clean", "not compromised", "is compromised", "was compromised", "safe"):
        assert phrase not in text, phrase
    assert "cipp's own rating" in text
