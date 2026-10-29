"""Build the index of Halo's public guides that Leafy searches (app/data/halo_guides_index.json).

Only titles, ids and the section each guide sits under are kept: the guides themselves are read live from usehalo.com when Leafy needs one, so nothing of Halo's text is copied into this repository.
Run: ``python scripts/build_halo_guide_index.py`` (one request at a time, a pause between them). Needs network access.
"""

from __future__ import annotations

import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://www.usehalo.com"
# The six sections linked from the Halo guides introduction (guide 2338).
ROOTS = {"459": "About Halo", "47": "Configuration Settings Guides", "479": "Integrations", "310": "On-Premises Guides", "45": "Security", "499": "Using and Configuring Halo"}
LINK = re.compile(r'href="/(guides|faq)/(\d+)[^"]*"[^>]*>(.*?)</a>', re.S)
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "halo_guides_index.json"
PAUSE = 0.4


def get(path: str) -> str:
    req = urllib.request.Request(f"{BASE}{path}", headers={"User-Agent": "A.C.O.R.N-guide-indexer (internal; contact the MSP)"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed host
        return resp.read().decode("utf-8", errors="ignore")


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def crawl() -> list[dict[str, str]]:
    guides: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    queue: list[tuple[str, str]] = list(ROOTS.items())
    while queue:
        fid, trail = queue.pop(0)
        if fid in seen:
            continue
        seen.add(fid)
        try:
            page = get(f"/faq/{fid}")
        except Exception as exc:  # noqa: BLE001
            print(f"faq {fid}: {exc}", file=sys.stderr)
            continue
        for kind, ident, label in LINK.findall(page):
            title = text(label)
            if not title or title.isdigit():
                continue
            if kind == "faq" and ident not in seen:
                queue.append((ident, f"{trail} > {title}"))
            elif kind == "guides" and ident not in guides:
                guides[ident] = {"id": ident, "title": title[:200], "section": trail[:300]}
        time.sleep(PAUSE)
        print(f"{len(seen)} sections read, {len(guides)} guides, {len(queue)} to go", file=sys.stderr)
    return sorted(guides.values(), key=lambda g: (g["section"], g["title"].lower()))


if __name__ == "__main__":
    index = crawl()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(index, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {len(index)} guides to {OUT}")
