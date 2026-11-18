"""The weekly compliance notice: addresses, web address, when it is due, and what it says (pure rules)."""

from datetime import UTC, datetime, timedelta

from app.services import compliance_notice as cn

NOW = datetime(2026, 11, 18, 9, tzinfo=UTC)


def item(kind="vendor_review", name="Acme Hosting", event="annual review", days=None, owner=None, link="/compliance/vendors"):
    return {"kind": kind, "name": name, "event": event, "owner": owner, "due": None if days is None else NOW + timedelta(days=days), "link": link}


def test_addresses_are_trimmed_lowered_deduplicated_and_only_real_ones_kept():
    got = cn.clean_emails([" Amy@X.com ", "amy@x.com", "not an address", "bob@x", "c@y.org", "d@e.com;f@g.com", ""])
    assert got == ["amy@x.com", "c@y.org"]
    assert cn.clean_emails(None) == [] and len(cn.clean_emails([f"p{i}@x.com" for i in range(50)])) == cn.MAX_EMAILS


def test_a_web_address_must_be_https_with_a_real_host_and_no_login_or_local_name():
    assert cn.webhook_problem(None) == "" and cn.webhook_problem("") == ""
    assert cn.webhook_problem("https://hooks.example.com/abc") == ""
    for bad in ("http://hooks.example.com/x", "ftp://x.example.com", "https://localhost/x", "https://nas.local/x", "https://x.internal/y", "https://user:pw@hooks.example.com/x", "https://intranet/x", "not a url"):
        assert cn.webhook_problem(bad) != "", bad
    assert cn.webhook_problem("https://hooks.example.com/" + "a" * 600) != ""


def test_a_notice_is_due_when_switched_on_and_not_sent_in_the_last_week():
    assert cn.due(True, None, NOW)
    assert not cn.due(False, None, NOW)
    assert not cn.due(True, NOW - timedelta(days=6, hours=23), NOW)
    assert cn.due(True, NOW - timedelta(days=7), NOW)
    assert cn.due(True, (NOW - timedelta(days=9)).replace(tzinfo=None), NOW), "a time with no zone is read as UTC"


def test_the_notice_lists_each_item_with_when_it_is_due_counts_the_overdue_ones_and_carries_the_same_list_as_json():
    items = [item(days=-3, owner="Amy"), item("access_review", "Entra review", "due", 0), item("risk_task", "Patch the VPN", "task", 5), item("audit_request", "SOC 2 sample", "request", None)]
    subject, text, payload = cn.digest(items, NOW, link="https://acorn.example/compliance", scope="Acme Dental")
    assert subject == "[A.C.O.R.N] 4 compliance action items waiting for Acme Dental, 1 overdue"
    assert "- Vendor review: Acme Hosting: annual review, 3 days overdue (owner: Amy)" in text
    assert "- Access review: Entra review: due, due today" in text
    assert "- Risk task: Patch the VPN: task, due in 5 days (2026-11-23)" in text
    assert "- Audit request: SOC 2 sample: request, no date" in text
    assert text.endswith("Open the Compliance page: https://acorn.example/compliance")
    assert payload["schema"] == "acorn.compliance_actions.v1" and payload["overdue"] == 1 and payload["scope"] == "Acme Dental"
    assert [i["name"] for i in payload["items"]] == ["Acme Hosting", "Entra review", "Patch the VPN", "SOC 2 sample"]
    assert payload["items"][0]["due"] == (NOW - timedelta(days=3)).isoformat() and payload["items"][3]["due"] is None


def test_one_item_reads_in_the_singular_and_a_long_list_is_cut_with_the_rest_counted():
    subject, text, _ = cn.digest([item(days=2)], NOW)
    assert subject == "[A.C.O.R.N] 1 compliance action item waiting" and "due in 2 days" in text
    many = [item(name=f"N{i}", days=i) for i in range(cn.MAX_LINES + 7)]
    _, long_text, payload = cn.digest(many, NOW)
    assert long_text.count("\n- ") + (1 if long_text.startswith("- ") else 0) == cn.MAX_LINES and "... and 7 more on the Compliance page." in long_text
    assert len(payload["items"]) == cn.MAX_LINES + 7, "the web address gets every item"
    assert cn.digest([item(days=-1)], NOW)[2]["overdue"] == 1
    assert "1 day overdue" in cn.digest([item(days=-1)], NOW)[1]
