"""The agreement rate per kind of action: counts, the rules for promote / keep / demote / too few, and the window."""

from datetime import UTC, datetime, timedelta

from app.services import autonomy_agreement as ag

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


def row(action="isolate_host", status="approved", days_ago=1, title="t"):
    return {"action": {"type": action} if action else {}, "title": title, "status": status, "created_at": NOW - timedelta(days=days_ago)}


def test_the_kind_of_action_comes_from_the_payload_then_the_title_then_unknown():
    assert ag.action_key({"type": " Isolate_Host "}) == "isolate_host"
    assert ag.action_key({"tool": "block_ip"}) == "block_ip"
    assert ag.action_key({}, "Disable account") == "disable account"
    assert ag.action_key(None, None) == "unknown"
    assert ag.action_key({"type": 5}, "") == "unknown"


def test_counts_each_status_and_an_expired_card_counts_against_agreement():
    rows = [row(status="approved")] * 6 + [row(status="denied")] + [row(status="expired")] + [row(status="pending")]
    (r,) = ag.summarize(rows, NOW)
    assert (r.proposed, r.approved, r.denied, r.expired, r.pending, r.decided) == (9, 6, 1, 1, 1, 8)
    assert r.agreement == 0.75, "6 approved of 8 decided; the pending one is not decided"
    assert r.suggestion == "demote"


def test_promote_needs_twenty_decided_and_ninety_five_percent():
    nineteen = [row()] * 19
    assert ag.summarize(nineteen, NOW)[0].suggestion == "keep", "100% but only 19 decided"
    twenty = [row()] * 20
    assert ag.summarize(twenty, NOW)[0].suggestion == "promote"
    nineteen_of_twenty = [row()] * 19 + [row(status="denied")]
    assert ag.summarize(nineteen_of_twenty, NOW)[0].agreement == 0.95
    assert ag.summarize(nineteen_of_twenty, NOW)[0].suggestion == "promote", "exactly 95% counts"
    eighteen_of_twenty = [row()] * 18 + [row(status="denied")] * 2
    assert ag.summarize(eighteen_of_twenty, NOW)[0].suggestion == "keep"


def test_too_few_decided_says_so_and_pending_only_has_no_rate():
    few = [row()] * 4
    assert ag.summarize(few, NOW)[0].suggestion == "too few"
    (r,) = ag.summarize([row(status="pending")] * 3, NOW)
    assert r.agreement is None and r.decided == 0 and r.suggestion == "too few"


def test_old_rows_are_left_out_and_kinds_are_listed_most_proposed_first():
    rows = [row(days_ago=ag.WINDOW_DAYS + 1)] * 5 + [row("block_ip")] * 3 + [row("disable_user")] * 2
    got = ag.summarize(rows, NOW)
    assert [r.action for r in got] == ["block_ip", "disable_user"]
