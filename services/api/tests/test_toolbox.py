"""The toolbox catalog and the check of a request (pure)."""

from app.services import toolbox as t


def test_every_tool_has_a_group_a_risk_and_fields_and_ids_are_unique():
    assert len({x.id for x in t.TOOLS}) == len(t.TOOLS)
    for x in t.TOOLS:
        assert x.group in t.GROUPS and x.risk in ("low", "medium", "high") and x.fields
    ids = {x.id for x in t.TOOLS}
    assert {"onboard_user", "offboard_user", "reset_mfa", "compromised_user", "litigation_hold"} <= ids
    assert all(x.risk == "high" for x in t.TOOLS if x.id in ("offboard_user", "compromised_user", "reset_mfa"))


def test_a_request_needs_every_field_and_a_real_email_where_one_is_asked_for():
    tool, args, why = t.check_request("reset_mfa", {"user": "ann@acme.com", "reason": "lost phone", "extra": "ignored"})
    assert tool and why is None and args == {"user": "ann@acme.com", "reason": "lost phone"}, "extra values are not kept"
    assert t.check_request("reset_mfa", {"user": "ann@acme.com"})[2] == "Why is needed."
    assert "email address" in t.check_request("reset_mfa", {"user": "ann", "reason": "x"})[2]
    assert "email address" in t.check_request("mail_forwarding", {"user": "a@b.co", "to": "not an address", "keep_copy": "yes"})[2]
    assert t.check_request("nope", {})[2] == "That tool does not exist."
    assert "too long" in t.check_request("out_of_office", {"user": "a@b.co", "message": "x" * 501, "until": "Monday"})[2]


def test_the_approval_card_shows_every_value_and_whether_it_can_be_undone():
    tool, args, _ = t.check_request("offboard_user", {"user": "bob@acme.com", "manager": "ann@acme.com", "when": "Friday 5pm"})
    title, text = t.approval_text(tool, "Acme", args)
    assert title == "Offboard a person: bob@acme.com"
    assert "Client: Acme" in text and "Who receives the mailbox and files (email address): ann@acme.com" in text and "Date and time to do it: Friday 5pm" in text
    assert text.endswith("Not easily reversed.")
    assert len(t.catalog()) == len(t.TOOLS) and t.catalog()[0]["fields"][0]["key"] == "user"
