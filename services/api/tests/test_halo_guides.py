"""Leafy's Halo guides: find a guide by its title, read it live from Halo's site, and never fetch anything that is not a guide in the index."""

from __future__ import annotations

import asyncio

import httpx
from app import copilot_tools as ct
from app.services import halo_guides as hg

ROWS = [
    {"id": "100", "title": "Recurring Invoices", "section": "Using and Configuring Halo > Billing"},
    {"id": "101", "title": "Automating Prices in Recurring Invoices", "section": "Using and Configuring Halo > Billing"},
    {"id": "102", "title": "Invoice Statuses", "section": "Using and Configuring Halo > Billing"},
    {"id": "200", "title": "Custom Automations", "section": "Using and Configuring Halo > Custom Automations"},
    {"id": "300", "title": "Setting up Two Factor Authentication", "section": "Security"},
]

PAGE = """<html><head><title>Guides - Recurring Invoices</title><style>.guide-raw, .guide-layout-code { display: none; }</style></head><body><nav>Menu Book Demo</nav>
<div class="guides-content"></div><div id="guide-raw" data-guide-id="" class="guide-raw"><div class="text-block-22">&lt;style&gt;p { margin: 0; }&lt;/style&gt;&lt;h2&gt;Recurring invoices&lt;/h2&gt;&lt;p&gt;Go to &lt;b&gt;Configuration&lt;/b&gt; &amp;gt; Billing.&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Pick a client&lt;/li&gt;&lt;li&gt;Set the schedule&lt;/li&gt;&lt;/ul&gt;</div></div><div class="guides-feedback-form-wrapper">Was this helpful?</div><script>var x = 1;</script></body></html>"""


def test_the_best_title_comes_first_and_a_guide_must_share_a_word():
    got = hg.search("how do I set up recurring invoices", rows=ROWS)
    assert [g["id"] for g in got][:2] == ["100", "101"], "the exact title beats the longer one that also matches"
    assert got[0]["url"] == "https://www.usehalo.com/guides/100"
    assert hg.search("recurring invoices", rows=ROWS)[-1]["id"] in {"101", "102"}
    assert hg.search("purple elephants", rows=ROWS) == []
    assert hg.search("the and of", rows=ROWS) == [], "only filler words: nothing to match"


def test_the_section_helps_find_a_guide_and_the_limit_is_kept():
    assert [g["id"] for g in hg.search("security", rows=ROWS)] == ["300"]
    assert len(hg.search("billing", limit=2, rows=ROWS)) == 2


def test_the_shipped_index_lists_real_guides():
    rows = hg.index()
    assert len(rows) > 500 and all(r["id"].isdigit() for r in rows)
    assert any("invoice" in r["title"].lower() for r in rows)
    assert hg.search("recurring invoices")[0]["title"].lower().startswith("recurring invoices") or hg.search("recurring invoices")


def test_the_guide_body_is_taken_from_the_page_without_the_menu_scripts_or_feedback_form():
    title, body = hg.extract_guide(PAGE)
    assert title == "Recurring Invoices"
    assert body.splitlines()[0] == "Recurring invoices"
    assert "Go to Configuration > Billing." in body and "Pick a client" in body
    assert (
        "Book Demo" not in body
        and "var x" not in body
        and "Was this helpful" not in body
        and "margin" not in body
        and "display: none" not in body
    )
    assert hg.extract_guide("<html><title>x</title><p>nothing</p></html>")[1] == ""


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_reading_a_guide_fetches_it_once_a_day_and_only_from_the_index(monkeypatch):
    monkeypatch.setattr(hg, "index", lambda: ROWS)
    hg._cache.clear()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, text=PAGE)

    async def run():
        async with _client(handler) as c:
            first = await hg.read_guide("100", c, now=1000.0)
            again = await hg.read_guide("100", c, now=1000.0 + 3600)
            later = await hg.read_guide("100", c, now=1000.0 + 90_000)
            bad = [await hg.read_guide(x, c) for x in ("999", "../x", "100/../../etc", "")]
            return first, again, later, bad

    first, again, later, bad = asyncio.run(run())
    assert first["url"] == "https://www.usehalo.com/guides/100" and "Pick a client" in first["text"]
    assert again is first, "kept for a day"
    assert seen == ["https://www.usehalo.com/guides/100"] * 2, "fetched again only after a day"
    assert all("error" in b for b in bad) and len(seen) == 2, "an id that is not in the index is never fetched"


def test_a_failing_site_or_a_page_without_a_guide_says_so_instead_of_inventing_one(monkeypatch):
    monkeypatch.setattr(hg, "index", lambda: ROWS)
    hg._cache.clear()

    async def run(handler):
        async with _client(handler) as c:
            return await hg.read_guide("100", c)

    assert "answered 503" in asyncio.run(run(lambda r: httpx.Response(503)))["error"]
    assert "could not reach" in asyncio.run(run(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))))["error"]
    assert "could not be found" in asyncio.run(run(lambda r: httpx.Response(200, text="<html><title>x</title></html>")))["error"]


def test_a_long_guide_is_cut_and_says_so(monkeypatch):
    monkeypatch.setattr(hg, "index", lambda: ROWS)
    hg._cache.clear()
    page = PAGE.replace("&lt;li&gt;Pick a client&lt;/li&gt;", "&lt;li&gt;" + "x" * 20000 + "&lt;/li&gt;")

    async def run():
        async with _client(lambda r: httpx.Response(200, text=page)) as c:
            return await hg.read_guide("100", c)

    got = asyncio.run(run())
    assert len(got["text"]) == hg.MAX_CHARS and got["truncated"] is True


def test_leafy_has_both_tools_with_a_permission_and_a_prompt_that_sends_halo_questions_to_them():
    names = {t["function"]["name"] for t in ct.COPILOT_TOOLS} if hasattr(ct, "COPILOT_TOOLS") else set()
    from app.api.v1.endpoints.copilot import _SYSTEM_PROMPT

    assert {"search_halo_guides", "read_halo_guide"} <= set(ct.TOOL_PERMISSIONS) and {"search_halo_guides", "read_halo_guide"} <= set(
        ct._COPILOT_TOOL_DISPATCH
    )
    assert not names or {"search_halo_guides", "read_halo_guide"} <= names
    assert "search_halo_guides" in _SYSTEM_PROMPT and "Never answer Halo setup questions from memory" in _SYSTEM_PROMPT


def test_the_search_tool_answers_with_guides_or_a_hint(monkeypatch):
    monkeypatch.setattr(hg, "index", lambda: ROWS)
    found = asyncio.run(ct.search_halo_guides(tenant_id="t", query="custom automations"))
    assert found["count"] >= 1 and found["guides"][0]["id"] == "200"
    none = asyncio.run(ct.search_halo_guides(tenant_id="t", query="zzzz"))
    assert none["count"] == 0 and "try other words" in none["note"]
