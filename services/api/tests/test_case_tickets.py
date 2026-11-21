"""The pure parts of case tickets (the database parts are in test_case_tickets_postgres.py)."""

from app.services import case_tickets


def test_ticket_numbers_are_digits_only():
    assert case_tickets.clean_ticket_number(" #12345 ") == "12345"
    assert case_tickets.clean_ticket_number("INC-1") is None
    assert case_tickets.clean_ticket_number("1" * 13) is None
    assert case_tickets.clean_ticket_number(None) is None


def test_a_case_has_a_ticket_only_when_a_halopsa_ticket_is_listed():
    assert not case_tickets.has_ticket([])
    assert not case_tickets.has_ticket(None)
    assert not case_tickets.has_ticket([{"system": "jira", "id": "X-1"}, {"id": ""}, "junk"])
    assert case_tickets.has_ticket([{"system": "halopsa", "id": "4711"}])
    assert case_tickets.has_ticket([{"id": "4711"}])  # a ticket with no system named is a HaloPSA one


def test_the_tickets_an_alert_carries_are_read_once_each_in_order():
    enrichment = {"manual_tickets": [{"system": "halopsa", "id": "2"}, {"system": "jira", "id": "9"}], "tickets": [{"id": "2"}, {"id": "1"}, {"id": "bad"}]}
    assert case_tickets.alert_ticket_numbers(enrichment) == ["2", "1"]
    assert case_tickets.alert_ticket_numbers(None) == []
    assert case_tickets.alert_ticket_numbers({"tickets": "nope"}) == []


def test_the_ticket_opened_from_a_case_names_the_case_and_the_person():
    summary, details = case_tickets.ticket_details("  Odd   logins ", "Seen at 3am", "INC-7", "hal@example.com")
    assert summary == "Odd logins"
    assert details.startswith("Seen at 3am") and "INC-7" in details and "hal@example.com" in details
    assert "Opened from an A.C.O.R.N case by" in case_tickets.ticket_details("t", None, None, "x")[1]
