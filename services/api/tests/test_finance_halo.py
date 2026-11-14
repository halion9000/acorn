"""Margin and ageing from the HaloPSA money snapshot: pure functions, money in whole cents."""

from datetime import date

from app.services.finance_halo import aging_from_halo, bucket_of, margin_from_halo

SNAPSHOT = {
    "recurring": [
        {
            "id": "7",
            "client_id": "12",
            "client_name": "Acme Dental",
            "period": 3,
            "lines": [
                {"item": "Managed Endpoint", "qty": 10, "unit_price": 25, "unit_cost": 9},
                {"item": "Backup", "qty": 2, "unit_price": 40, "unit_cost": 0},
            ],
        },
        {
            "id": "8",
            "client_id": "12",
            "client_name": "Acme Dental",
            "period": 3,
            "lines": [{"item": "Phones", "qty": 4, "unit_price": 15.5, "unit_cost": 6.25}],
        },
        {
            "id": "9",
            "client_id": "30",
            "client_name": "Birch Law",
            "period": 3,
            "lines": [{"item": "Managed Endpoint", "qty": 5, "unit_price": 25, "unit_cost": 20}],
        },
        {
            "id": "10",
            "client_id": "31",
            "client_name": "Cedar Co",
            "period": 3,
            "lines": [{"item": "Mystery", "qty": 1, "unit_price": 100, "unit_cost": 0}],
        },
    ],
    "invoices": [],
}


def test_margin_counts_only_costed_lines_and_names_the_ones_with_no_cost():
    out = margin_from_halo(SNAPSHOT)
    acme = next(c for c in out["clients"] if c["client_name"] == "Acme Dental")
    # Revenue shows everything billed; margin is worked out on the lines that have a cost.
    assert acme["revenue"] == "392.00"  # 250 + 80 + 62
    assert acme["costed_revenue"] == "312.00"  # 250 + 62
    assert acme["cost"] == "115.00"  # 90 + 25
    assert acme["margin"] == "197.00"
    assert acme["margin_percent"] == 63.1
    assert acme["lines_without_cost"] == ["Backup"]
    assert acme["recurring_invoices"] == 2


def test_the_lowest_margin_comes_first_and_a_client_with_nothing_costed_goes_last_without_a_percentage():
    out = margin_from_halo(SNAPSHOT)
    assert [c["client_name"] for c in out["clients"]] == ["Birch Law", "Acme Dental", "Cedar Co"]
    cedar = out["clients"][-1]
    assert cedar["margin_percent"] is None and cedar["lines_without_cost"] == ["Mystery"]
    assert out["totals"]["revenue"] == "617.00"  # 392 + 125 + 100
    assert out["totals"]["margin"] == "222.00"  # 197 + 25


def test_an_empty_snapshot_is_empty_not_an_error():
    out = margin_from_halo({"recurring": [], "invoices": []})
    assert out["clients"] == [] and out["totals"]["margin_percent"] is None


TODAY = date(2026, 11, 13)


def test_how_late_an_invoice_is_sorts_it_into_a_bucket():
    assert bucket_of(None, TODAY) == "not_due"
    assert bucket_of(date(2026, 11, 14), TODAY) == "not_due"
    assert bucket_of(date(2026, 11, 13), TODAY) == "not_due"
    assert bucket_of(date(2026, 11, 12), TODAY) == "1_30"
    assert bucket_of(date(2026, 10, 14), TODAY) == "1_30"  # 30 days
    assert bucket_of(date(2026, 10, 13), TODAY) == "31_60"
    assert bucket_of(date(2026, 9, 14), TODAY) == "31_60"  # 60 days
    assert bucket_of(date(2026, 9, 13), TODAY) == "61_90"  # 61 days
    assert bucket_of(date(2026, 8, 15), TODAY) == "61_90"  # 90 days
    assert bucket_of(date(2026, 8, 14), TODAY) == "over_90"  # 91 days


def test_ageing_groups_what_is_owed_per_client_worst_first_and_totals_it():
    snap = {
        "recurring": [],
        "invoices": [
            {
                "client_id": "12",
                "client_name": "Acme Dental",
                "number": "INV-1",
                "due": "2026-08-01T00:00:00",
                "amount_due": 500,
                "total": 500,
            },
            {
                "client_id": "12",
                "client_name": "Acme Dental",
                "number": "INV-2",
                "due": "2026-11-01T00:00:00",
                "amount_due": 100.25,
                "total": 300,
            },
            {
                "client_id": "30",
                "client_name": "Birch Law",
                "number": "INV-3",
                "due": "2026-12-01T00:00:00",
                "amount_due": 900,
                "total": 900,
            },
            {"client_id": "30", "client_name": "Birch Law", "number": "INV-4", "due": None, "amount_due": 0, "total": 10},
        ],
    }
    out = aging_from_halo(snap, TODAY)
    assert [c["client_name"] for c in out["clients"]] == ["Acme Dental", "Birch Law"]
    acme = out["clients"][0]
    assert acme["owed"] == "600.25"
    assert acme["buckets"]["over_90"] == "500.00" and acme["buckets"]["1_30"] == "100.25"
    assert [(i["number"], i["days_late"]) for i in acme["invoices"]] == [("INV-1", 104), ("INV-2", 12)]
    assert out["clients"][1]["buckets"]["not_due"] == "900.00"
    assert out["totals"]["owed"] == "1500.25"
    assert out["totals"]["over_90"] == "500.00"
