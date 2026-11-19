"""The Tickets, Finance and Customer Insights pages of Metrics: Ticket Resolution, Ticket Volume Analysis, the open-ticket breakdown, Monthly Invoicing, Customer Experience, Monthly Licensing and User Roles.
Numbers worked out by hand."""

from datetime import UTC, datetime

from app.services import metrics_customers as mc
from app.services import metrics_tickets as mt

W1, W2 = "2026-10-26", "2026-11-02"

DETAIL = {
    "weeks": [W1, W2],
    "rows": [
        {
            "week": W1,
            "client_id": "5",
            "client_name": "Acme",
            "type": "Incident",
            "category": "Email",
            "priority": "Medium",
            "created": 4,
            "resolved": 3,
            "resolution_hours": 7.5,
            "resolved_with_time": 3,
        },
        {
            "week": W1,
            "client_id": "6",
            "client_name": "Birch",
            "type": "Request",
            "category": "Hardware",
            "priority": "Low",
            "created": 2,
            "resolved": 2,
            "resolution_hours": 20,
            "resolved_with_time": 2,
        },
        {
            "week": W2,
            "client_id": "5",
            "client_name": "Acme",
            "type": "Incident",
            "category": "Network",
            "priority": "High",
            "created": 6,
            "resolved": 5,
            "resolution_hours": 5.0,
            "resolved_with_time": 5,
        },
        {
            "week": W2,
            "client_id": "6",
            "client_name": "Birch",
            "type": "Incident",
            "category": "Email",
            "priority": "Medium",
            "created": 1,
            "resolved": 0,
            "resolution_hours": 0,
            "resolved_with_time": 0,
        },
    ],
    "open": [
        {"client_id": "5", "client_name": "Acme", "status": "In Progress", "priority": "High", "count": 2},
        {"client_id": "5", "client_name": "Acme", "status": "Waiting", "priority": "Low", "count": 1},
        {"client_id": "6", "client_name": "Birch", "status": "In Progress", "priority": "Medium", "count": 3},
    ],
    "stale": [
        {
            "ticket_id": "1",
            "client_name": "Acme",
            "agent": "Dan",
            "title": "Printer",
            "priority": "Low",
            "status": "Waiting",
            "age_days": 45,
        },
        {"ticket_id": "2", "client_name": "Birch", "agent": "Dan", "title": "VPN", "priority": "Medium", "status": "New", "age_days": 90},
        {"ticket_id": "3", "client_name": "Acme", "agent": "", "title": "Phone", "priority": "High", "status": "New", "age_days": 31},
    ],
}
STAFF = {
    "rows": [
        {"week": W1, "engineer": "Dan", "closed": 31, "surveys": {"total_surveys": 2, "positive": 1, "neutral": 1, "negative": 0}},
        {"week": W2, "engineer": "Dan", "closed": 9},
        {"week": W1, "engineer": "Vic", "closed": 1},
        {"week": W2, "engineer": "Vic", "closed": 0, "surveys": {"total_surveys": 0}},
    ]
}


def test_ticket_volume_counts_created_tickets_by_type_category_month_and_client():
    r = mt.ticket_volume(DETAIL, 1)
    assert r["months"] == ["2026-10", "2026-11"] and r["total_created"] == 13
    assert [(x["name"], x["total"], x["by_month"]) for x in r["by_type"]] == [
        ("Incident", 11, {"2026-10": 4, "2026-11": 7}),
        ("Request", 2, {"2026-10": 2}),
    ]
    assert [(x["name"], x["total"]) for x in r["by_category"]] == [("Network", 6), ("Email", 5), ("Hardware", 2)]
    assert r["per_month"] == [{"month": "2026-10", "created": 6}, {"month": "2026-11", "created": 7}]
    assert r["by_client"] == [{"client": "Acme", "created": 10}, {"client": "Birch", "created": 3}]
    assert r["priority_last_60_days"] == [
        {"priority": "High", "created": 6},
        {"priority": "Medium", "created": 5},
        {"priority": "Low", "created": 2},
    ]


def test_stale_tickets_are_counted_by_tech_oldest_first_and_can_be_narrowed_to_one_tech():
    r = mt.ticket_volume(DETAIL, 1)
    assert r["stale_by_tech"] == [{"tech": "Dan", "tickets": 2}, {"tech": "Unassigned", "tickets": 1}]
    assert [s["ticket_id"] for s in r["stale"]] == ["2", "1", "3"] and r["techs"] == ["Dan", "Unassigned"]
    one = mt.ticket_volume(DETAIL, 1, "Dan")
    assert [s["ticket_id"] for s in one["stale"]] == ["2", "1"] and len(one["stale_by_tech"]) == 2, "the counts per tech stay whole"
    assert [s["agent"] for s in mt.ticket_volume(DETAIL, 1, "Unassigned")["stale"]] == ["Unassigned"]


def test_what_is_open_now_is_split_by_status_and_priority_for_all_clients_or_one():
    r = mt.open_breakdown(DETAIL)
    assert r["total"] == 6 and r["by_status"] == [{"status": "In Progress", "tickets": 5}, {"status": "Waiting", "tickets": 1}]
    assert r["by_priority"] == [{"priority": "Medium", "tickets": 3}, {"priority": "High", "tickets": 2}, {"priority": "Low", "tickets": 1}]
    one = mt.open_breakdown(DETAIL, "5")
    assert one["total"] == 3 and one["by_priority"] == [{"priority": "High", "tickets": 2}, {"priority": "Low", "tickets": 1}]
    assert mt.open_breakdown(None)["total"] == 0


def test_ticket_resolution_gives_resolved_per_member_per_month_and_the_average_hours_to_resolve_per_client():
    r = mt.ticket_resolution(DETAIL, STAFF, 1)
    assert r["months"] == ["2026-10", "2026-11"]
    assert [(m["engineer"], m["total"], m["by_month"]) for m in r["members"]] == [
        ("Dan", 40, {"2026-10": 31, "2026-11": 9}),
        ("Vic", 1, {"2026-10": 1, "2026-11": 0}),
    ]
    assert r["resolution_by_client"] == [
        {"client": "Birch", "hours": 10.0, "tickets": 2},
        {"client": "Acme", "hours": 1.6, "tickets": 8},
    ], "(7.5 + 5) / 8 for Acme; tickets with no time are not averaged in"
    assert mt.ticket_resolution(None, None, 3) == {"months": [], "members": [], "resolution_by_client": []}


INVOICES = {
    "months": ["2026-09", "2026-10"],
    "rows": [
        {"month": "2026-09", "client_name": "Acme", "item": "M365", "category": "Licensing", "quantity": 10, "amount": 220},
        {"month": "2026-10", "client_name": "Acme", "item": "M365", "category": "Licensing", "quantity": 12, "amount": 264},
        {"month": "2026-10", "client_name": "Acme", "item": "Managed Services", "category": "Managed", "quantity": 1, "amount": 1500},
        {"month": "2026-10", "client_name": "Birch", "item": "M365", "category": "Licensing", "quantity": 5, "amount": 110},
    ],
}


def test_monthly_invoicing_gives_the_trend_the_billing_categories_and_each_clients_lines():
    r = mt.monthly_invoicing(INVOICES, 1)
    assert r["months"] == ["2026-10"] and r["total"] == 1874.0 and r["trend"] == [{"month": "2026-10", "amount": 1874.0}]
    assert r["by_category"] == [{"category": "Managed", "amount": 1500.0}, {"category": "Licensing", "amount": 374.0}]
    acme, birch = r["clients"]
    assert (acme["client"], acme["total"]) == ("Acme", 1764.0) and [(i["item"], i["amount"]) for i in acme["items"]] == [
        ("Managed Services", 1500.0),
        ("M365", 264.0),
    ]
    assert (birch["client"], birch["total"]) == ("Birch", 110.0)
    two = mt.monthly_invoicing(INVOICES, 2)
    assert two["total"] == 2094.0 and [t["month"] for t in two["trend"]] == ["2026-09", "2026-10"]
    assert mt.monthly_invoicing(None, 3)["clients"] == []


CSAT = {
    "months": ["2026-09", "2026-10"],
    "rows": [
        {"company": "Acme", "month": "2026-09", "positive": 1, "neutral": 0, "negative": 0, "total": 1},
        {"company": "Acme", "month": "2026-10", "positive": 2, "neutral": 1, "negative": 1, "total": 4},
        {"company": "Birch", "month": "2026-10", "positive": 0, "neutral": 0, "negative": 1, "total": 1},
    ],
    "recent": [
        {"company": "Acme", "date": "2026-10-12", "sentiment": "negative", "comment": "Slow"},
        {"company": "Acme", "date": "2026-10-20", "sentiment": "positive", "comment": "Great"},
    ],
}


def test_customer_experience_breaks_csat_down_by_company_member_and_month():
    r = mc.customer_experience(CSAT, STAFF, 1)
    assert r["months"] == ["2026-10"]
    assert [(c["company"], c["responses"], c["csat"], c["neutral_percent"], c["negative_percent"]) for c in r["by_company"]] == [
        ("Acme", 4, 50.0, 25.0, 25.0),
        ("Birch", 1, 0.0, 0.0, 100.0),
    ]
    assert (r["overall"]["responses"], r["overall"]["csat"]) == (5, 40.0)
    assert [(m["month"], m["responses"]) for m in r["by_month"]] == [("2026-10", 5)]
    assert [(m["member"], m["responses"], m["csat"]) for m in r["by_member"]] == [
        ("Dan", 2, 50.0)
    ], "a member with no surveys is not listed"
    assert [x["comment"] for x in r["recent"]] == ["Great", "Slow"], "newest first"


def test_a_sentiment_filter_keeps_only_those_responses_in_the_counts_and_the_comments():
    r = mc.customer_experience(CSAT, STAFF, 1, "negative")
    assert [(c["company"], c["responses"]) for c in r["by_company"]] == [("Acme", 1), ("Birch", 1)]
    assert r["overall"]["responses"] == 2 and [x["comment"] for x in r["recent"]] == ["Slow"]
    nothing = mc.customer_experience({"months": ["2026-10"], "rows": [], "recent": []}, None, 1)
    assert nothing["overall"] is None and nothing["by_company"] == []
    assert mc.customer_experience(CSAT, STAFF, 1, "bogus")["sentiment"] == "all"


def _at(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


CURRENT = [
    {"client_id": "c1", "source": "m365", "item": "Business Premium", "unit": "user", "count": 12},
    {"client_id": "c1", "source": "ninjaone", "item": "Windows workstations", "unit": "device", "count": 20},
    {"client_id": "c2", "source": "m365", "item": "Business Premium", "unit": "user", "count": 5},
]
HISTORY = [
    {"client_id": "c1", "source": "m365", "item": "Business Premium", "count": 10, "observed_at": _at(2026, 9, 10)},
    {"client_id": "c1", "source": "m365", "item": "Business Premium", "count": 12, "observed_at": _at(2026, 10, 5)},
    {"client_id": "c1", "source": "ninjaone", "item": "Windows workstations", "count": 20, "observed_at": _at(2026, 10, 20)},
    {"client_id": "c2", "source": "m365", "item": "Business Premium", "count": 4, "observed_at": _at(2026, 9, 15)},
    {"client_id": "c2", "source": "m365", "item": "Business Premium", "count": 0, "observed_at": _at(2026, 9, 30)},
]
NOW = _at(2026, 11, 15)
NAMES = {"c1": "Acme", "c2": "Birch"}


def test_this_months_licensing_is_what_is_counted_now_by_client_and_item():
    r = mc.licensing_matrix(CURRENT, HISTORY, NAMES, "2026-11", NOW)
    assert r["as_of"] == "now"
    assert [(c["client"], c["counts"]) for c in r["clients"]] == [
        ("Acme", {"m365|Business Premium": 12, "ninjaone|Windows workstations": 20}),
        ("Birch", {"m365|Business Premium": 5}),
    ]
    assert [(i["key"], i["unit"], i["total"]) for i in r["items"]] == [
        ("m365|Business Premium", "user", 17),
        ("ninjaone|Windows workstations", "device", 20),
    ]


def test_an_earlier_months_licensing_is_each_count_as_of_the_end_of_that_month():
    r = mc.licensing_matrix(CURRENT, HISTORY, NAMES, "2026-09", NOW)
    assert r["as_of"] == "2026-10-01"
    assert [(c["client"], c["counts"]) for c in r["clients"]] == [
        ("Acme", {"m365|Business Premium": 10})
    ], "ninjaone was first counted in October; Birch's count had gone to 0 by the end of September"
    oct_ = mc.licensing_matrix(CURRENT, HISTORY, NAMES, "2026-10", NOW)
    assert oct_["clients"][0]["counts"] == {"m365|Business Premium": 12, "ninjaone|Windows workstations": 20}
    assert mc.month_end("2026-12") == _at(2027, 1, 1)


def test_user_roles_count_who_holds_each_directory_role_per_client_and_skip_empty_ones():
    payload = {
        "clients": [
            {
                "client_id": "5",
                "client_name": "Acme",
                "roles": [
                    {
                        "role": "Global Administrator",
                        "members": [
                            {"name": "Amy", "upn": "amy@a.example", "enabled": True},
                            {"name": "Bob", "upn": "bob@a.example", "enabled": False},
                        ],
                    },
                    {"role": "Exchange Administrator", "members": [{"name": "Amy", "upn": "amy@a.example"}]},
                ],
            },
            {
                "client_id": "6",
                "client_name": "Birch",
                "roles": [
                    {"role": "Helpdesk Administrator", "members": []},
                    {"role": "Global Administrator", "members": [{"name": "Cy", "upn": "cy@b.example"}]},
                ],
            },
            {"client_id": "7", "client_name": "Cedar", "roles": []},
        ]
    }
    r = mc.user_roles(payload)
    assert r["roles"] == [{"role": "Global Administrator", "total": 3}, {"role": "Exchange Administrator", "total": 1}]
    assert [(c["client"], c["counts"]) for c in r["clients"]] == [
        ("Acme", {"Global Administrator": 2, "Exchange Administrator": 1}),
        ("Birch", {"Global Administrator": 1}),
    ]
    assert r["clients"][0]["members"]["Global Administrator"][1] == {"name": "Bob", "upn": "bob@a.example", "enabled": False}
    assert mc.user_roles(None) == {"roles": [], "clients": []}


def test_stale_tickets_carry_their_type_opened_day_and_idle_days():
    detail = {"weeks": [], "rows": [], "open": [], "stale": [{"ticket_id": "9", "client_name": "Acme", "agent": "Dan", "title": "VPN", "priority": "Low", "status": "On Hold", "age_days": 90, "type": "Project", "opened": "2026-08-01", "last_activity": "2026-11-10", "idle_days": 4}, {"ticket_id": "8", "client_name": "Acme", "agent": "Dan", "title": "x", "priority": "", "status": "", "age_days": 50}]}
    first, second = mt.ticket_volume(detail, 1)["stale"]
    assert (first["type"], first["opened"], first["last_activity"], first["idle_days"]) == ("Project", "2026-08-01", "2026-11-10", 4)
    assert second["idle_days"] is None and second["last_activity"] == ""
