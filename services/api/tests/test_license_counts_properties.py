"""Rules that must hold for ANY input to the billing reconcile and the totals, checked over a few hundred generated cases (a fixed seed, so a failure is repeatable).

The example tests in test_license_counts.py pin particular answers; these pin the arithmetic: nothing billed is lost or counted twice, a total is the sum of its parts, and the order
of the input never changes the answer."""

import random

from app.services import license_counts as lc

SOURCES = ["ninjaone", "huntress", "cipp", "addigy"]
ITEMS = ["Seats", "Agents", "Macs", "Windows workstations", "Mailboxes"]
INVOICE_ITEMS = [f"Line {i}" for i in range(8)]


def case(rng: random.Random):
    held = [{"source": s, "item": i, "count": rng.randint(0, 500)} for s in SOURCES for i in ITEMS if rng.random() < 0.6]
    billed = [{"item": name, "count": rng.randint(0, 500)} for name in rng.sample(INVOICE_ITEMS, rng.randint(0, len(INVOICE_ITEMS)))]
    mapping = {}
    for name in INVOICE_ITEMS:
        roll = rng.random()
        if roll < 0.25:
            continue  # nobody has mapped this line
        if roll < 0.4:
            mapping[name] = []  # saved as "no tool counts this"
            continue
        pairs = rng.sample([(s, i) for s in SOURCES for i in ITEMS], rng.randint(1, 3))
        mapping[name] = [{"source": s, "item": i} for s, i in pairs]
    return billed, held, mapping


def test_every_billed_line_lands_in_exactly_one_place_and_the_arithmetic_holds():
    rng = random.Random(20261110)
    for _ in range(300):
        billed, held, mapping = case(rng)
        out = lc.reconcile(billed, held, mapping)
        have = {(h["source"], h["item"]): h["count"] for h in held}
        compared = {r["invoice_item"] for r in out["rows"]}
        waiting = {u["item"] for u in out["unmapped"]}
        set_aside = {b["item"] for b in billed if b["item"] in mapping and not mapping[b["item"]]}
        assert compared | waiting | set_aside == {b["item"] for b in billed}, "no billed line is lost"
        assert not (compared & waiting) and not (compared & set_aside) and not (waiting & set_aside), "and none is in two places"
        bill = {b["item"]: b["count"] for b in billed}
        for r in out["rows"]:
            assert r["billed"] == bill[r["invoice_item"]]
            assert r["counted"] == sum(p["count"] for p in r["parts"])
            assert r["difference"] == r["counted"] - r["billed"]
            for p in r["parts"]:
                assert p["count"] == have.get((p["source"], p["item"]), 0), "a part is what the tool holds, or zero when it holds nothing"
        for u in out["unmapped"]:
            assert u["billed"] == bill[u["item"]]
        gaps = [abs(r["difference"]) for r in out["rows"]]
        assert gaps == sorted(gaps, reverse=True), "the biggest difference is first"


def test_the_order_of_the_input_never_changes_the_answer():
    rng = random.Random(7)
    for _ in range(150):
        billed, held, mapping = case(rng)
        first = lc.reconcile(billed, held, mapping)
        shuffled_billed, shuffled_held = billed[:], held[:]
        rng.shuffle(shuffled_billed)
        rng.shuffle(shuffled_held)
        second = lc.reconcile(shuffled_billed, shuffled_held, mapping)
        assert first["rows"] == second["rows"]
        assert sorted(first["unmapped"], key=lambda u: u["item"]) == sorted(second["unmapped"], key=lambda u: u["item"])


def test_totals_add_up_whatever_the_rows_are():
    rng = random.Random(99)
    for _ in range(300):
        rows = []
        for _client in range(rng.randint(0, 12)):
            for s in SOURCES:
                for i in ITEMS:
                    if rng.random() < 0.3:
                        rows.append(
                            {
                                "source": s,
                                "item": i,
                                "unit": "each",
                                "count": rng.randint(0, 300),
                                "available": rng.choice([None, rng.randint(0, 50)]),
                                "then": rng.choice([None, rng.randint(0, 300)]),
                            }
                        )
        out = lc.totals(rows)
        assert [(t["source"], t["item"]) for t in out] == sorted({(r["source"], r["item"]) for r in rows}), "one line per tool and item, in order"
        assert sum(t["total"] for t in out) == sum(r["count"] for r in rows)
        assert sum(t["clients"] for t in out) == len(rows)
        for t in out:
            mine = [r for r in rows if (r["source"], r["item"]) == (t["source"], t["item"])]
            known = [r["available"] for r in mine if r["available"] is not None]
            assert t["available"] == (sum(known) if known else None), "no 'available' figure is invented when no client reported one"
            if any(r["then"] is None for r in mine):
                assert t["change"] is None, "a change is not shown when any client's earlier count is unknown"
            else:
                assert t["change"] == t["total"] - sum(r["then"] for r in mine)


def test_unusual_never_fires_on_small_counts_or_no_change_and_is_the_same_up_or_down():
    rng = random.Random(3)
    for _ in range(500):
        previous = rng.randint(0, 400)
        step = rng.randint(0, 200)
        assert lc.unusual(previous, previous) is False
        assert lc.unusual(previous + step, previous) == lc.unusual(previous - step, previous), "a rise and a fall of the same size are judged alike"
        if previous < lc.UNUSUAL_MIN_PREVIOUS:
            assert lc.unusual(previous + step, previous) is False
    assert lc.unusual(10, None) is False
