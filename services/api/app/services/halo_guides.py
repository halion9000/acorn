"""Halo's public guides, for Leafy: find the right guide by what it is called, then read it live.

``app/data/halo_guides_index.json`` lists every guide (id, title, the section it sits under; built by scripts/build_halo_guide_index.py). Nothing of the guides' own text is stored here: ``read_guide`` fetches
one page from usehalo.com when a question needs it, takes the guide body out of the page, and keeps it in memory for a day. The address is built from the numeric id of a guide in the index and nothing else, so a
question can never send this to another host.
"""

from __future__ import annotations

import html
import json
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

BASE = "https://www.usehalo.com"
INDEX_FILE = Path(__file__).resolve().parents[1] / "data" / "halo_guides_index.json"
MAX_CHARS = 7000
CACHE_SECONDS = 24 * 3600
CACHE_MAX = 64
FETCH_TIMEOUT = 15.0
_STOP = frozenset(
    "a an the and or of to in on for with how do does i we you my our is are can what which where when why set up setup use using halo halopsa psa".split()
)
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


@lru_cache(maxsize=1)
def index() -> list[dict[str, str]]:
    """Every guide: ``{"id", "title", "section"}``. Empty (never an error) when the file is missing."""
    try:
        rows = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and str(r.get("id", "")).isdigit() and r.get("title")]


def _words(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in _STOP or len(w) < 2:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def search(query: str, limit: int = 6, rows: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """The guides whose title (most) or section (a little) share words with the question, best first. A guide must match at least one word."""
    wanted = set(_words(query))
    if not wanted:
        return []
    scored: list[tuple[float, str, dict[str, str]]] = []
    for g in rows if rows is not None else index():
        title, section = set(_words(g["title"])), set(_words(g.get("section", "")))
        hit_title, hit_section = wanted & title, wanted & section
        if not hit_title and not hit_section:
            continue
        # Every wanted word found in the title beats a long title that matches one; the section only breaks ties.
        score = 3.0 * len(hit_title) + 1.0 * len(hit_section) + 2.0 * (len(hit_title) / len(wanted)) - 0.01 * len(title)
        scored.append((score, g["title"].lower(), g))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [
        {"id": g["id"], "title": g["title"], "section": g.get("section", ""), "url": f"{BASE}/guides/{g['id']}"}
        for _s, _t, g in scored[: max(1, min(limit, 15))]
    ]


_BLOCKS = re.compile(r"(?i)</?(?:p|div|br|li|ul|ol|h[1-6]|tr|table|pre|blockquote)[^>]*>")


def extract_guide(page: str) -> tuple[str, str]:
    """``(title, body)`` from a guide page. The guide sits in the element with id guide-raw, written as ESCAPED html (its tags arrive as ``&lt;p&gt;``), before the page's own scripts and feedback form."""
    title_match = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    title = re.sub(r"\s+", " ", html.unescape(title_match.group(1))).strip() if title_match else ""
    title = re.sub(r"^Guides\s*-\s*", "", title)
    tag = re.search(r"""<[^>]*\bid=["']guide-raw["'][^>]*>""", page) or re.search(r"""<[^>]*class=["']guide-raw["'][^>]*>""", page)
    if tag is None:
        return title, ""
    start = tag.end()
    ends = [e for e in (page.find(m, start) for m in ('id="guide-output"', "guides-feedback-form-wrapper", "<script")) if e > start]
    chunk = page[start : min(ends) if ends else start + 400_000]
    chunk = html.unescape(chunk)  # the guide's own markup, as html
    chunk = re.sub(r"<[^>]*$", "", chunk)  # the cut can land inside the page's next tag
    chunk = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", chunk)
    text = html.unescape(re.sub(r"<[^>]+>", "", _BLOCKS.sub("\n", chunk)))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return title, text


async def read_guide(guide_id: str, client: httpx.AsyncClient | None = None, now: float | None = None) -> dict[str, Any]:
    """One guide's title, link and text (cut at ``MAX_CHARS``), or ``{"error": ...}``. Only a guide that is in the index is fetched."""
    gid = str(guide_id).strip()
    known = {g["id"]: g for g in index()}
    if gid not in known:
        return {"error": f"no Halo guide {gid!r}: search the guides first and use an id from the results"}
    clock = now if now is not None else time.time()
    hit = _cache.get(gid)
    if hit is not None and clock - hit[0] < CACHE_SECONDS:
        return hit[1]
    url = f"{BASE}/guides/{gid}"
    own = client is None
    http = client or httpx.AsyncClient(
        timeout=FETCH_TIMEOUT, headers={"User-Agent": "A.C.O.R.N-Leafy (reads Halo's public guides)"}, follow_redirects=False
    )
    try:
        res = await http.get(url)
    except httpx.HTTPError as exc:
        return {"error": f"could not reach the Halo guides: {type(exc).__name__}", "url": url}
    finally:
        if own:
            await http.aclose()
    if res.status_code != 200:
        return {"error": f"the Halo guides answered {res.status_code}", "url": url}
    title, body = extract_guide(res.text)
    if not body:
        return {"error": "the guide's text could not be found on the page", "url": url, "title": title or known[gid]["title"]}
    out = {
        "id": gid,
        "title": title or known[gid]["title"],
        "section": known[gid].get("section", ""),
        "url": url,
        "text": body[:MAX_CHARS],
        "truncated": len(body) > MAX_CHARS,
    }
    if len(_cache) >= CACHE_MAX:
        _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
    _cache[gid] = (clock, out)
    return out
