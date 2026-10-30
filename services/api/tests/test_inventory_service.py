"""Reading Live Oak's exported SharePoint lists, and placing each customer's rows under a client."""

from __future__ import annotations

from datetime import date

import pytest
from app.services import inventory as inv
from app.services.client_matching import Candidate

# The three shapes the exports come in, as they are written (BOM, multi-line notes, HTML in notes, M/D/YYYY dates).
LO = (
    '﻿"ID","Customer","EntryName","SerialNo","Barcode","Quantity","Notes","Status","Tags","AssetType","PartNo","HasCharger","CheckedOutDate","CheckedInDate","Person","Image","Ninja","CPU","Memory","HDD"\n'
    '"13","Austin Gamblers","Dell Pro Max 16","BSH7SB4","SD2YDT1004","1","32 GB memory\n1 TB SSD","Checked Out",,,,"FALSE",,,,,,,,\n'
    '"14","Austin Gamblers","Dell Pro Max 16 Plus","DPHSDC4","SD2YDT0923","1",,"Checked Out",,,"MB16250","TRUE",,,,,"https://app.ninjarmm.com/#/deviceDashboard/9500/overview","Intel(R) Core(TM) Ultra 7 265HX (20 cores)","32.0 GB","953.87 GB"\n'
    '"15","LO Inventory (Office)","Hard Drive","",,"3",,"Archived",,"Equipment",,,"1/1/2026",,,,,,,\n'
)
NUC = (
    '"ID","Customer","Computer Name","Serial No.","Status","Initial Deployment Date","Redeployment Date","Barcode","Model No.","Site Location","Person","CheckedInDate","CheckedOutDate","Notes","Image","Accounting Treatment"\n'
    '"232","Talking Monkey, Inc.","NUC-MONKEY","MXL5193139","CheckedOut","9/9/2025",,,"HP Pro Mini 400 G9 Desktop PC","Austin","Braxton Barley",,,,,\n'
    '"240","","NUC-SPARE","","Offline","11/20/2024","2/1/2025",,"OptiPlex 7050","Main",,,,,,"Capitalized"\n'
)
PER_CLIENT = (
    '"EntryName","Device Model","Deployed To","SerialNo","Barcode","Quantity","Notes","Status","Tags","AssetType","PartNo","HasCharger","CheckedOutDate","CheckedInDate","Person","Image","Ninja","CPU","Memory","HDD"\n'
    '"X1 Carbon 13th Gen","X1 Carbon 13th Gen","Arjun Barua","PF5QMPC",,"1",,"Checked Out","Deployed","Lenovo",,,,,,,,,,\n'
    '"MacBook Air 13\'\'","M1","spare","C17G3K39",,"1","ARCHIVED - older than 3 years<p><br></p>","Checked In Damaged",,"Mac",,"yes",,"1/1/2026",,,,,"8GB","256GB SSD"\n'
)


def test_a_stock_list_row_becomes_an_item_with_its_notes_dates_and_machine_details():
    rows = inv.parse_csv(LO, "stock")
    assert len(rows) == 3
    first, second, third = (r.item for r in rows)
    assert (first["name"], first["serial"], first["status"], first["quantity"], first["external_ref"]) == (
        "Dell Pro Max 16",
        "BSH7SB4",
        "checked_out",
        1,
        "13",
    )
    assert first["notes"] == "32 GB memory\n1 TB SSD" and first["has_charger"] is False
    assert (second["part_no"], second["has_charger"], second["cpu"], second["memory"], second["storage"]) == (
        "MB16250",
        True,
        "Intel(R) Core(TM) Ultra 7 265HX (20 cores)",
        "32.0 GB",
        "953.87 GB",
    )
    assert second["ninja_url"] == "https://app.ninjarmm.com/#/deviceDashboard/9500/overview"
    assert (third["status"], third["quantity"], third["category"], third["serial"], third["checked_out_at"]) == (
        "retired",
        3,
        "Equipment",
        None,
        date(2026, 1, 1),
    )
    assert rows[0].customer_name == "Austin Gamblers"


def test_a_nuc_row_keeps_its_site_person_model_and_deployment_dates_and_a_blank_customer():
    monkey, spare = inv.parse_csv(NUC, "nuc")
    assert (monkey.item["name"], monkey.item["model"], monkey.item["site"], monkey.item["person"], monkey.item["deployed_at"]) == (
        "NUC-MONKEY",
        "HP Pro Mini 400 G9 Desktop PC",
        "Austin",
        "Braxton Barley",
        date(2025, 9, 9),
    )
    assert monkey.customer_name == "Talking Monkey, Inc." and monkey.item["status"] == "checked_out"
    assert (spare.customer_name, spare.item["status"], spare.item["redeployed_at"], spare.item["accounting_treatment"]) == (
        None,
        "offline",
        date(2025, 2, 1),
        "Capitalized",
    )


def test_a_per_client_list_has_no_customer_and_takes_deployed_to_as_the_person_and_the_html_out_of_notes():
    carbon, air = inv.parse_csv(PER_CLIENT, "stock")
    assert (
        carbon.customer_name is None
        and carbon.item["person"] == "Arjun Barua"
        and carbon.item["tags"] == ["Deployed"]
        and carbon.item["category"] == "Lenovo"
    )
    assert air.item["person"] == "spare" and air.item["notes"] == "ARCHIVED - older than 3 years"
    assert (air.item["status"], air.item["tags"], air.item["has_charger"], air.item["checked_in_at"]) == (
        "checked_in",
        ["damaged"],
        True,
        date(2026, 1, 1),
    )


def test_statuses_are_read_in_the_lists_own_words_with_or_without_spaces():
    pairs = [
        ("Checked Out", "checked_out"),
        ("CheckedOut", "checked_out"),
        ("Checked In", "checked_in"),
        ("CheckedIn", "checked_in"),
        ("Archived", "retired"),
        ("Decommissioned", "retired"),
        ("Offline", "offline"),
        ("", "checked_in"),
        ("weird", "checked_in"),
    ]
    assert [inv.parse_status(s)[0] for s, _ in pairs] == [want for _, want in pairs]
    assert inv.parse_status("Checked In Damaged") == ("checked_in", ["damaged"])


def test_a_row_with_nothing_to_name_it_is_a_problem_and_blank_lines_are_skipped_and_a_wrong_kind_is_refused():
    rows = inv.parse_csv('"Customer","EntryName","SerialNo","Model No."\n"Acme",,,\n,,,\n"Acme","Switch",,\n', "stock")
    assert [bool(r.problems) for r in rows] == [True, False]
    with pytest.raises(ValueError):
        inv.parse_csv("a,b\n1,2\n", "gadgets")


def test_clean_text_removes_tags_and_entities_keeps_lines_and_cuts_to_the_limit():
    assert inv.clean_text("<p>a</p><p>b</p><br>c&amp;d&nbsp;e", 100) == "a\nb\nc&d e"
    assert inv.clean_text("<p><br></p>", 50) is None
    assert inv.clean_text("x" * 50, 10) == "x" * 10


CLIENTS = [Candidate("t-acme", "Acme Dental, LLC"), Candidate("t-birch", "Birch Law"), Candidate("t-birch2", "Birch Lawn Care")]
OWN = "t-own"


def test_a_customer_goes_to_the_client_with_the_same_name_ignoring_punctuation_and_company_words():
    assert inv.place_customer("Acme Dental", OWN, CLIENTS) == inv.Placement("t-acme", "exact")
    assert inv.place_customer("ACME DENTAL, INC.", OWN, CLIENTS).tenant_id == "t-acme"


def test_live_oaks_own_names_and_no_customer_are_the_owners_stock_and_an_unknown_name_is_kept_unmatched_with_suggestions():
    assert inv.place_customer("LO Inventory (Office)", OWN, CLIENTS) == inv.Placement(OWN, "own")
    assert inv.place_customer(None, OWN, CLIENTS).how == "own"
    near = inv.place_customer("Birch Law Firm", OWN, CLIENTS)
    assert (near.tenant_id, near.how) == (OWN, "unmatched") and near.suggestions and near.suggestions[0][0] in ("t-birch", "t-birch2")
    assert inv.place_customer("Totally Unknown Co", OWN, CLIENTS).suggestions == []


def test_a_persons_choice_and_a_files_default_client_come_before_any_matching_and_skip_drops_the_rows():
    assert inv.place_customer("Acme Dental", OWN, CLIENTS, {"acme dental": "t-birch"}).tenant_id == "t-birch"
    assert inv.place_customer("Whatever", OWN, CLIENTS, {"whatever": inv.OWN}) == inv.Placement(OWN, "chosen")
    assert inv.place_customer("Whatever", OWN, CLIENTS, {"whatever": inv.SKIP}).tenant_id is None
    assert inv.place_customer(None, OWN, CLIENTS, None, "t-acme") == inv.Placement("t-acme", "chosen")


def test_customers_are_counted_once_each_whatever_the_spelling_and_serials_match_ignoring_case_and_punctuation():
    rows = inv.parse_csv(LO, "stock") + inv.parse_csv(LO, "stock")
    assert inv.customers_of(rows) == {"Austin Gamblers": 4, "LO Inventory (Office)": 2}
    assert inv.same_item({"serial": "abc-123"}, {"serial": "ABC 123"}) and not inv.same_item({"serial": None}, {"serial": None})
    assert inv.same_item({"external_ref": "5", "serial": "x"}, {"external_ref": "5", "serial": "y"})
    assert not inv.same_item({"external_ref": "5"}, {"external_ref": "6", "serial": "same"})


def test_only_an_item_that_is_here_can_be_checked_out_and_only_one_that_is_out_can_be_checked_in():
    assert [inv.can_check_out(s) for s in inv.STATUSES] == [True, False, True, False]
    assert [inv.can_check_in(s) for s in inv.STATUSES] == [False, True, False, False]


def test_a_placeholder_or_shared_serial_is_never_an_identifier():
    assert (
        inv.usable_serial("Default string") == ""
        and inv.usable_serial("0000000") == ""
        and inv.usable_serial("ab") == ""
        and inv.usable_serial(None) == ""
    )
    assert inv.usable_serial("MXL-5193 139") == "mxl5193139"
    items = [
        {"serial": "KAMRUI"},
        {"serial": "kamrui"},
        {"serial": "MXL5193139"},
        {"serial": None},
        {"serial": "Default string"},
        {"serial": "Default string"},
    ]
    assert inv.shared_serials(items) == {
        "kamrui"
    }, "the maker's name on two NUCs is shared; a real serial held once is not; a placeholder was never a serial"
