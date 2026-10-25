from datetime import UTC, datetime, timedelta

from app.services.license_counts import changes, count_at, delta, totals, window_start

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def rep(item, count, unit="device", available=None):
    return {"item": item, "unit": unit, "count": count, "available": available}


def test_a_first_report_records_every_item_with_no_previous_count():
    c = changes({}, [rep("Macs", 4), rep("Business Premium", 25, "licence", 2)])
    assert [(h["item"], h["count"], h["previous_count"]) for h in c["history"]] == [("Macs", 4, None), ("Business Premium", 25, None)]
    assert [u["item"] for u in c["upserts"]] == ["Macs", "Business Premium"] and c["removed"] == []


def test_only_a_changed_count_adds_history_and_it_keeps_the_old_count():
    c = changes({"Macs": 4, "Windows": 10}, [rep("Macs", 4), rep("Windows", 12)])
    assert [(h["item"], h["previous_count"], h["count"]) for h in c["history"]] == [("Windows", 10, 12)]
    assert len(c["upserts"]) == 2, "every reported item is stored, changed or not"


def test_an_item_that_is_no_longer_reported_is_removed_and_recorded_as_zero():
    c = changes({"Macs": 4, "Old": 3}, [rep("Macs", 4)])
    assert c["removed"] == ["Old"]
    assert c["history"] == [{"item": "Old", "unit": "other", "count": 0, "previous_count": 3}]


def test_a_repeated_item_in_one_report_counts_once():
    assert len(changes({}, [rep("Macs", 4), rep("Macs", 9)])["upserts"]) == 1


def h(days_after_t0, count):
    return {"observed_at": T0 + timedelta(days=days_after_t0), "count": count}


def test_the_count_at_a_date_is_the_newest_row_at_or_before_it():
    rows = [h(0, 10), h(10, 12), h(20, 8)]
    assert count_at(rows, 8, T0, T0 + timedelta(days=15), T0) == 12
    assert count_at(rows, 8, T0, T0 + timedelta(days=10), T0) == 12, "a change on that very day counts"
    assert count_at(rows, 8, T0, T0 + timedelta(days=25), T0) == 8


def test_an_item_with_no_row_that_old_was_unchanged_or_new():
    when = T0 + timedelta(days=30)
    assert count_at([], 7, T0, when, T0) == 7, "seen before the date and never changed"
    assert count_at([h(40, 9)], 9, T0 + timedelta(days=40), when, T0) == 0, "appeared after the date, while it was tracked"
    assert count_at([h(40, 9)], 9, T0 + timedelta(days=40), when, T0 + timedelta(days=35)) is None, "tracking had not started: unknown"


def test_delta_is_unknown_when_the_old_count_is():
    assert delta(12, 10) == 2 and delta(8, 10) == -2 and delta(5, None) is None


def test_totals_add_across_clients_with_the_change_and_unknown_when_any_client_is_unknown():
    rows = [
        {"source": "cipp", "item": "BP", "unit": "licence", "count": 25, "available": 2, "then": 20},
        {"source": "cipp", "item": "BP", "unit": "licence", "count": 10, "available": 0, "then": 10},
        {"source": "ninjaone", "item": "Macs", "unit": "device", "count": 4, "available": None, "then": None},
    ]
    t = {(r["source"], r["item"]): r for r in totals(rows)}
    assert t[("cipp", "BP")] == {"source": "cipp", "item": "BP", "unit": "licence", "clients": 2, "total": 35, "available": 2, "change": 5}
    assert t[("ninjaone", "Macs")]["change"] is None and t[("ninjaone", "Macs")]["available"] is None


def test_the_window_is_at_least_a_day_and_at_most_400():
    now = datetime(2026, 10, 25, tzinfo=UTC)
    assert window_start(now, 0) == now - timedelta(days=1)
    assert window_start(now, 9999) == now - timedelta(days=400)
