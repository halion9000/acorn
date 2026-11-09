"""The proposal log's rules (autonomy plan, foundation 1 and the evidence rule).

Every action an agent proposes or takes is logged with the rung of the autonomy ladder it landed on and the evidence it rests on. Two rules live here so the API and the tests share them:

  * EVIDENCE RULE: a proposal with no usable evidence link is refused, so an agent cannot act on a hunch. Evidence is a list of ``{"label": text, "url": optional text}``; an entry needs a label (or a url).
  * ``shadow`` means "would have done": nothing happened. Only a person can later say what they made of it (accepted, edited, rejected, expired); an agent cannot mark its own proposal.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

RUNGS = ("shadow", "suggest", "ask", "act_tell", "act_quiet")
OUTCOMES = ("none", "accepted", "edited", "rejected", "expired")
MAX_EVIDENCE = 20


class EvidenceError(ValueError):
    """The proposal has no usable evidence."""


def clean_evidence(raw: Any) -> list[dict[str, str]]:
    """The evidence as stored: entries with a label or url, text trimmed and capped, at most 20. Raises EvidenceError when nothing usable remains (pure)."""
    out: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                item = {"label": item}
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()[:200]
            url = str(item.get("url") or "").strip()[:500]
            if not label and not url:
                continue
            entry = {"label": label or url}
            if url:
                entry["url"] = url
            out.append(entry)
            if len(out) == MAX_EVIDENCE:
                break
    if not out:
        raise EvidenceError("A proposal needs at least one piece of evidence (a label, a link or both): an action with nothing behind it is refused.")
    return out


def tally(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the log's header: how many per rung, how many per outcome, and how many shadow proposals still await a person's verdict (pure)."""
    rungs = Counter(r.get("rung") for r in rows)
    outcomes = Counter(r.get("outcome") for r in rows)
    return {
        "total": len(rows),
        "by_rung": {k: rungs.get(k, 0) for k in RUNGS},
        "by_outcome": {k: outcomes.get(k, 0) for k in OUTCOMES},
        "shadow_unreviewed": sum(1 for r in rows if r.get("rung") == "shadow" and r.get("outcome") == "none"),
    }
