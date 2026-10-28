"""A client's documentation (IT Glue) in plain words: what is stored, how a question becomes a search, and when Leafy looks."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app import copilot_tools as ct
from app.api.v1.endpoints.client_documents import ClientDocIn, ClientDocsReport
from app.services import client_docs as cd
from pydantic import ValidationError


def test_text_loses_control_characters_and_blank_runs_and_is_cut():
    assert cd.clean_text("a\x00b\x07c") == "abc", "a NUL byte would stop Postgres storing the row"
    assert cd.clean_text("one   \n\n\n\n\ntwo\t\n") == "one\n\ntwo"
    assert cd.clean_text("x" * 50, limit=10) == "x" * 10
    assert cd.clean_text(None) == "" and cd.clean_text("   ") == ""


def test_a_question_becomes_its_letters_and_digits_once_each_and_nothing_that_could_break_the_query():
    assert cd.search_terms("Do you use an onboarding guide for Airport Security Park?") == [
        "do", "you", "use", "an", "onboarding", "guide", "for", "airport", "security", "park",
    ]  # fmt: skip
    assert cd.search_terms("vpn vpn VPN") == ["vpn"]
    assert cd.search_terms("a ' | & ! ( ) : * x") == [], "single characters and punctuation are not terms"
    assert cd.search_terms("x') OR 1=1 --") == ["or"], "operators and quotes are dropped, only words stay"
    assert len(cd.search_terms(" ".join(f"word{i}" for i in range(40)))) == cd.MAX_TERMS


def test_the_search_matches_on_any_word_and_is_empty_when_there_are_no_words():
    assert cd.tsquery_text(["vpn", "firewall"]) == "vpn | firewall"
    assert cd.tsquery_text([]) is None
    assert cd.tsquery_text(["bad term", "ok"]) == "ok", "a term that is not plain letters and digits never reaches the query"


def test_a_question_that_names_a_client_is_pinned_to_that_client_and_a_general_one_is_not():
    park, school, tec = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    clients = [(park, "Airport Security Park, LLC"), (school, "Hill Country Christian School of Austin"), (tec, "Tecovas, Inc.")]
    assert cd.clients_named("do you use an onboarding guide for airport security park?", clients) == [park]
    assert cd.clients_named("what is the wifi password policy at Tecovas and the hill country christian school of austin", clients) == [
        tec,
        school,
    ]
    assert cd.clients_named("how do we reset a firewall", clients) == []
    assert cd.clients_named("airport security", clients) == [], "part of a name is not the client"
    assert cd.clients_named("anything", [(uuid.uuid4(), "AB")]) == [], "a name too short to be told apart is never matched"


def test_a_batch_cuts_a_huge_body_instead_of_refusing_it_and_refuses_what_is_malformed():
    big = ClientDocIn(id="d1", kind="document", title="Runbook", body="y" * (cd.MAX_BODY * 3))
    assert len(big.body) == cd.MAX_BODY
    with pytest.raises(ValidationError):
        ClientDocIn(id="d1", kind="Not A Kind", title="t")
    with pytest.raises(ValidationError):
        ClientDocsReport(vendor="itglue", items=[ClientDocIn(id=str(i), kind="document", title="t") for i in range(101)])


def test_what_looks_like_a_secret_is_blanked_before_it_is_stored_and_ordinary_text_is_not():
    text = "Admin login\nusername: bob\nPassword: Sup3rS3cret!\nwifi pwd = hunter2\napi key: abc123\nThe VPN is on port 443.\n"
    out = cd.redact_secrets(text)
    assert "Sup3rS3cret" not in out and "hunter2" not in out and "abc123" not in out
    assert "username: bob" in out and "The VPN is on port 443." in out, "only the secret part of a line is blanked"
    assert out.count("[redacted]") == 3
    key = "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nIBAAKC\n-----END RSA PRIVATE KEY-----\nafter"
    assert cd.redact_secrets(key) == "before\n[private key redacted]\nafter"
    assert cd.redact_secrets("A password is required for every account.") == "A password is required for every account."


def test_a_password_entry_is_described_as_masked_with_its_link_and_never_its_value():
    text = ct.format_docs_snapshot(
        [
            {
                "client": "Tecovas",
                "kind": "password",
                "title": "Microsoft 365 admin",
                "url": "https://liveoak.itglue.com/1987544/passwords/16465978",
                "snippet": "Username: admin@tecovas.com",
            }
        ]
    )
    assert text is not None
    assert (
        "Microsoft 365 admin (a password entry in IT Glue; the password itself is masked there, open the link to reveal it) https://liveoak.itglue.com/1987544/passwords/16465978"
        in text
    )
    assert "Username: admin@tecovas.com" in text


def test_the_model_is_given_the_passages_with_the_client_the_document_and_the_link():
    text = ct.format_docs_snapshot(
        [
            {
                "client": "Airport Security Park",
                "kind": "document",
                "title": "Onboarding guide",
                "url": "https://x.itglue.com/1/docs/2",
                "snippet": "Step 1: create the account",
            }
        ]
    )
    assert text is not None
    assert "Airport Security Park: Onboarding guide (document) https://x.itglue.com/1/docs/2" in text
    assert "Step 1: create the account" in text
    assert "Do not invent" in text
    assert ct.format_docs_snapshot([]) is None


@pytest.mark.asyncio
async def test_a_greeting_is_not_searched_but_a_question_is_and_a_short_one_naming_a_client_is():
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    run = AsyncMock(return_value={"results": [{"client": "C", "kind": "document", "title": "T", "snippet": "s"}]})
    with patch.object(ct, "execute_copilot_tool", run), patch.object(ct, "_names_a_client", AsyncMock(return_value=False)):
        assert await ct.docs_snapshot(tenant_id=str(user.tenant_id), user=user, message="hi there") is None
        run.assert_not_called()
        assert await ct.docs_snapshot(tenant_id=str(user.tenant_id), user=user, message="how do we onboard a new hire") is not None
        run.assert_awaited_once()
    with patch.object(ct, "execute_copilot_tool", run), patch.object(ct, "_names_a_client", AsyncMock(return_value=True)):
        assert await ct.docs_snapshot(tenant_id=str(user.tenant_id), user=user, message="airport security park?") is not None


@pytest.mark.asyncio
async def test_a_person_who_may_not_read_alerts_gets_no_documentation_and_a_failure_gives_none():
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    denied = AsyncMock(return_value={"error": "permission denied: search_client_docs requires alerts:read"})
    with patch.object(ct, "execute_copilot_tool", denied):
        assert await ct.docs_snapshot(tenant_id=str(user.tenant_id), user=user, message="how do we onboard a new hire") is None


def test_the_tool_is_registered_with_the_same_permission_as_reading_alerts():
    assert ct.TOOL_PERMISSIONS["search_client_docs"] == "alerts:read"
    assert "search_client_docs" in ct._COPILOT_TOOL_DISPATCH
    assert any(t["function"]["name"] == "search_client_docs" for t in ct.COPILOT_TOOL_SCHEMAS)


@pytest.mark.asyncio
async def test_a_failed_documentation_lookup_never_breaks_the_chat():
    user = SimpleNamespace(tenant_id=uuid.uuid4())
    with patch.object(ct, "execute_copilot_tool", AsyncMock(side_effect=ConnectionError("database down"))):
        assert await ct.docs_snapshot(tenant_id=str(user.tenant_id), user=user, message="how do we onboard a new hire") is None
