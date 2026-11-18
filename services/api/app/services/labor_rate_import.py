"""Matching a list of "name, hourly rate" to the agents HaloPSA has (pure).

The burdened rate sheet names people the way payroll does ("Alexander Leslie Caico") or the way HaloPSA does ("Alex Caico"); A.C.O.R.N prices time by HaloPSA agent id. A name matches an agent when it is the same name
once case, punctuation and spacing are ignored; or, failing that, when the last word is the same and the first word is the same or a shortening of the other ("Alexander Leslie Caico" and "Alex Caico" are
"Alexander Caico", but "Cadence Alexander" and "Lake Alexander" are not: their last word is Alexander, and "Alexandra Holt" is not "Alexander Caico"). A name that fits more than one agent, or none, is not guessed: it is
listed as unmatched so a person can say who it is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


def _words(name: Any) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).split() if w]


def exact_key(name: Any) -> str:
    return "".join(_words(name))


def _first_last(name: Any) -> tuple[str, str] | None:
    w = _words(name)
    return (w[0], w[-1]) if len(w) >= 2 else None


def _same_first(a: str, b: str) -> bool:
    """The same first name, or one a shortening of the other (alex / alexander), at least three letters."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return a == b or (len(short) >= 3 and long_.startswith(short))


@dataclass(frozen=True)
class Matched:
    agent_id: str
    name: str
    rate: Decimal


def parse_rate(value: Any) -> Decimal | None:
    """An hourly rate from text or a number ("$72.24", "72.239", 55): two decimals, not negative, at most 10,000; None when it is not one."""
    try:
        d = Decimal(str(value).replace("$", "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    if not d.is_finite() or d < 0 or d > 10000:
        return None
    return d.quantize(Decimal("0.01"))


def match_rates(agents: list[dict[str, Any]], rows: list[tuple[str, Any]]) -> tuple[list[Matched], list[str]]:
    """The rows that name exactly one agent, and the names of those that name none or several, or whose rate is not a rate. An agent named twice keeps the last rate given."""
    usable = [a for a in agents if str(a.get("id") or "").strip()]
    by_exact: dict[str, list[dict[str, Any]]] = {}
    for a in usable:
        by_exact.setdefault(exact_key(a.get("name")), []).append(a)
    chosen: dict[str, Matched] = {}
    unmatched: list[str] = []
    for name, raw in rows:
        rate = parse_rate(raw)
        hits = by_exact.get(exact_key(name), []) if exact_key(name) else []
        if not hits:
            fl = _first_last(name)
            if fl:
                hits = [a for a in usable if (afl := _first_last(a.get("name"))) and afl[1] == fl[1] and _same_first(afl[0], fl[0])]
        if rate is None or len(hits) != 1:
            unmatched.append(str(name).strip()[:120])
            continue
        a = hits[0]
        chosen[str(a["id"])] = Matched(str(a["id"]), str(a.get("name") or ""), rate)
    return list(chosen.values()), unmatched
