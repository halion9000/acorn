"""The pure rules of questionnaires: splitting pasted questions, matching a question to the answer library, and the CSV a customer gets back. No database here.

Matching is by shared words (not by any model): the words of a question that carry meaning (not "do", "you", "the" and so on) are compared with those of each library question, and a library answer is only offered when
at least half of the words line up. An offered answer is a DRAFT: nothing is approved until a person approves it, and a question with no good match is left blank rather than answered with a guess.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any

MIN_SCORE = 50  # percent of shared words needed before a library answer is offered
MAX_QUESTIONS = 500
STOP = frozenset(
    "a an and are as at be by can could do does for from has have how if in is it its of on or our please shall should that the their there these this to us we what when where which who will with would you your".split()
)
_WORD = re.compile(r"[a-z0-9]+")
_NUMBERING = re.compile(r"^\s*(?:\(?\d{1,3}[.)\]]|\(?[a-z][.)]|[-*•])\s+", re.I)


def words(text: str) -> frozenset[str]:
    """The words of a question that carry meaning (pure)."""
    return frozenset(w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1)


def split_questions(text: str) -> list[str]:
    """Questions pasted one to a line: numbering and bullets removed, blank lines and repeats dropped, at most MAX_QUESTIONS (pure)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        q = _NUMBERING.sub("", raw).strip()
        key = q.lower()
        if len(q) >= 3 and key not in seen:
            seen.add(key)
            out.append(q[:2000])
    return out[:MAX_QUESTIONS]


def score(a: frozenset[str], b: frozenset[str]) -> int:
    """How much of the shorter question's words the other holds, in whole percent (0 when either has none)."""
    if not a or not b:
        return 0
    return round(100 * len(a & b) / min(len(a), len(b)))


def best_match(question: str, library: list[Any]) -> tuple[Any | None, int]:
    """The library entry whose question shares the most words with this one, and the percent, or (None, 0) when none reaches MIN_SCORE. Ties go to the entry reviewed most recently, then the first listed."""
    mine = words(question)
    ranked = []
    for index, entry in enumerate(library):
        reviewed = getattr(entry, "last_reviewed", None)
        ranked.append((score(mine, words(entry.question)), reviewed.toordinal() if reviewed else 0, -index, entry))
    if not ranked:
        return None, 0
    best = max(ranked, key=lambda r: r[:3])
    return (best[3], best[0]) if best[0] >= MIN_SCORE else (None, 0)


def csv_text(rows: list[tuple[int, str, str, str]]) -> str:
    """The questions and answers as CSV for the customer: number, question, answer, status. A cell that would run as a formula in a spreadsheet is made text."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["No.", "Question", "Answer", "Status"])
    for n, q, a, st in rows:
        w.writerow([n, _safe(q), _safe(a), st])
    return out.getvalue()


def _safe(v: str) -> str:
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
