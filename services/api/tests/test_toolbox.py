"""The toolbox catalog and the check of a request (pure)."""

from app.services import toolbox as t


def test_every_tool_has_a_group_a_risk_and_fields_and_ids_are_unique():
    assert len({x.id for x in t.TOOLS}) == len(t.TOOLS)
    for x in t.TOOLS:
        assert x.group in t.GROUPS and x.risk in ("low", "medium", "high") and x.fields
        assert all(f.kind in t.KINDS for f in x.fields)
        assert all(f.options for f in x.fields if f.kind == "choice"), "a choice field lists its choices"
    ids = {x.id for x in t.TOOLS}
    assert {"onboard_user", "offboard_user", "reset_mfa", "compromised_user", "litigation_hold"} <= ids
    assert all(x.risk == "high" for x in t.TOOLS if x.id in ("offboard_user", "compromised_user", "reset_mfa"))


def test_free_text_is_left_only_for_what_a_person_must_say():
    free = {(x.id, f.key) for x in t.TOOLS for f in x.fields if f.kind in ("text", "longtext")}
    assert not any(k in ("user", "grantee", "manager", "to", "mailbox", "members") for _, k in free), "people are picked, never typed"
    onboard = {f.key: f.kind for f in t.BY_ID["onboard_user"].fields}
    assert onboard["email_domain"] == "domain" and onboard["supervisor"] == "user" and onboard["copy_from"] == "user" and onboard["start_date"] == "datetime"
    assert onboard["shared_mailboxes"] == "users" and onboard["username_format"] == "choice" and len(onboard) >= 20, "the form follows Rewst's onboarding workflow"
    offboard = {f.key: f.kind for f in t.BY_ID["offboard_user"].fields}
    assert offboard["convert_to_shared"] == "choice" and offboard["onedrive_to"] == "user" and offboard["when"] == "datetime" and offboard["forward_to"] == "email"
    assert offboard["remove_licenses"] == "choice" and offboard["reset_mfa"] == "choice" and offboard["internal_reply"] == "longtext"


def test_a_request_needs_every_required_field_and_a_real_email_where_one_is_asked_for():
    tool, args, why = t.check_request("reset_mfa", {"user": "ann@acme.com", "reason": "lost phone", "extra": "ignored"})
    assert tool and why is None and args == {"user": "ann@acme.com", "reason": "lost phone"}, "extra values are not kept"
    assert t.check_request("reset_mfa", {"user": "ann@acme.com"})[2] == "Why is needed."
    assert "email address" in t.check_request("reset_mfa", {"user": "ann", "reason": "x"})[2]
    assert "email address" in t.check_request("mail_forwarding", {"user": "a@b.co", "to": "not an address", "keep_copy": "Yes"})[2]
    assert t.check_request("nope", {})[2] == "That tool does not exist."
    assert "too long" in t.check_request("out_of_office", {"user": "a@b.co", "message": "x" * 501, "until": "2026-12-01T09:00"})[2]


def test_a_choice_a_date_and_a_list_of_people_must_fit_their_kind():
    base = {"user": "a@b.co", "to": "out@side.org", "keep_copy": "Yes"}
    assert t.check_request("mail_forwarding", base)[2] is None, "an outside address is allowed where the kind is email"
    assert "one of: Yes, No" in t.check_request("mail_forwarding", {**base, "keep_copy": "maybe"})[2]
    assert "date and time" in t.check_request("out_of_office", {"user": "a@b.co", "message": "away", "until": "Monday"})[2]
    shared = {"user": "sales@acme.com", "members": "ann@acme.com, bob@acme.com"}
    assert t.check_request("shared_mailbox", shared)[1]["members"] == "ann@acme.com, bob@acme.com"
    assert "email addresses" in t.check_request("shared_mailbox", {**shared, "members": "ann@acme.com, bob"})[2]
    assert "too many" in t.check_request("shared_mailbox", {**shared, "members": ",".join(f"p{i}@a.co" for i in range(21))})[2]
    assert t.check_request("shared_mailbox", {"user": "sales@acme.com"})[1] == {"user": "sales@acme.com"}, "an empty optional field is dropped"


def test_onboarding_and_offboarding_take_the_whole_form():
    onboard = {"first_name": "Ann", "last_name": "Lee", "email_domain": "acme.com", "start_date": "2026-12-01T08:00"}
    tool, args, why = t.check_request("onboard_user", onboard)
    assert why is None and args == onboard, "everything else is optional"
    full = {**onboard, "supervisor": "bob@acme.com", "copy_from": "cy@acme.com", "shared_mailboxes": "sales@acme.com, info@acme.com", "shared_mailbox_access": "Full access and send as", "username_format": "flast", "vip": "No"}
    tool, args, why = t.check_request("onboard_user", full)
    assert why is None and args["shared_mailboxes"] == "sales@acme.com, info@acme.com"
    title, text = t.approval_text(tool, "Acme", args)
    assert title == "Onboard a new person: Ann Lee" and "Same license and groups as: cy@acme.com" in text and "Kind of shared mailbox access: Full access and send as" in text
    assert t.check_request("onboard_user", {**onboard, "email_domain": "not a domain"})[2] == "Email domain must be a domain name."
    assert "Username format must be one of" in t.check_request("onboard_user", {**onboard, "username_format": "random"})[2]
    assert t.check_request("onboard_user", {k: v for k, v in onboard.items() if k != "last_name"})[2] == "Last name is needed."
    off = {"user": "bob@acme.com"}
    assert t.check_request("offboard_user", off)[1] == off, "only the person is required"
    assert "Convert the mailbox to a shared mailbox must be one of" in t.check_request("offboard_user", {**off, "convert_to_shared": "Maybe"})[2]
    assert "email address" in t.check_request("offboard_user", {**off, "forward_to": "nobody"})[2]


def test_the_approval_card_shows_every_value_and_whether_it_can_be_undone():
    off = {"user": "bob@acme.com", "when": "2026-12-05T17:00", "convert_to_shared": "Yes", "remove_licenses": "No", "onedrive_to": "ann@acme.com"}
    tool, args, _ = t.check_request("offboard_user", off)
    title, text = t.approval_text(tool, "Acme", args)
    assert title == "Offboard a person: bob@acme.com"
    assert "Client: Acme" in text and "Give access to the OneDrive files to: ann@acme.com" in text and "Do it at: 2026-12-05T17:00" in text
    assert "Forward new mail to" not in text, "a field left empty is not shown"
    assert text.endswith("Not easily reversed.")
    assert len(t.catalog()) == len(t.TOOLS) and t.catalog()[0]["fields"][0]["key"] == "user" and t.catalog()[0]["fields"][0]["kind"] == "user"


def test_the_pickers_list_members_first_and_the_domains_by_use():
    rows = [
        ("zed@acme.com", "Zed", True, "Member"),
        ("ann@acme.com", "Ann", True, "Member"),
        ("old@acme.com", "Old", False, "Member"),
        ("ext@other.org", "Ext", True, "Guest"),
        ("bob@acme.net", None, True, "Member"),
        ("", "No address", True, None),
        ("cy@acme.com", "Cy", True, None),
    ]
    out = t.people_and_domains(rows)
    assert [p["email"] for p in out["people"]] == ["ann@acme.com", "bob@acme.net", "cy@acme.com", "zed@acme.com", "old@acme.com", "ext@other.org"]
    assert out["people"][1]["name"] == "bob@acme.net", "a missing name falls back to the address"
    assert out["domains"] == ["acme.com", "acme.net"], "guests do not add a domain; the most used comes first"


def test_the_group_is_picked_from_the_clients_groups_and_the_rules_are_picked_from_the_persons_rules():
    assert {f.key: f.kind for f in t.BY_ID["group_membership"].fields}["group"] == "group"
    assert {f.key: f.kind for f in t.BY_ID["remove_inbox_rules"].fields} == {"user": "user", "rules": "rules", "reason": "text"}
    assert t.BY_ID["remove_inbox_rules"].reversible is False


def test_removing_inbox_rules_needs_at_least_one_and_at_most_thirty_and_shows_each_by_name():
    ok = {"user": "ann@acme.com", "rules": "Forward all\nHide"}
    tool, args, why = t.check_request("remove_inbox_rules", ok)
    assert why is None and args == ok
    assert "Rules to remove: Forward all; Hide" in t.approval_text(tool, "Acme", args)[1]
    assert t.check_request("remove_inbox_rules", {"user": "ann@acme.com", "rules": " \n "})[2] == "Rules to remove is needed."
    assert "between 1 and 30" in t.check_request("remove_inbox_rules", {"user": "ann@acme.com", "rules": "\n".join(f"r{i}" for i in range(31))})[2]
    assert t.check_request("remove_inbox_rules", {"user": "ann@acme.com", "rules": "\n".join(f"rule number {i} " * 3 for i in range(30))})[2] is None, "a long list of long names still fits"
