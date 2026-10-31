"""Finding a client by the name a person typed, which is rarely the stored name exactly ("XtremeMD" for "Xstreme MD", "birch law" for "Birch Law, PLLC").

A match ignores case, spaces and punctuation; a name that merely contains what was typed fits; and a name that is one or two letters off (a missing, extra or changed letter) fits when what was typed is long enough
for that to be safe (5 letters or more tolerate one slip, 9 or more tolerate two). Shorter words must be contained exactly, so "abc" does not wander onto a similar client.
"""

from __future__ import annotations

import re
from collections.abc import Hashable, Mapping
from typing import TypeVar

K = TypeVar("K", bound=Hashable)


def normalize(text: str | None) -> str:
    """Lower case with everything but letters and digits removed."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _closest_substring_distance(needle: str, hay: str, limit: int) -> int:
    """The fewest letter edits (insert, remove, change) that turn ``needle`` into some stretch of ``hay``; stops early once it is over ``limit``."""
    # Approximate substring matching: the first row is zero so the stretch may start anywhere in ``hay``.
    previous = [0] * (len(hay) + 1)
    for i, ch in enumerate(needle, start=1):
        current = [i] + [0] * len(hay)
        for j, hc in enumerate(hay, start=1):
            current[j] = min(previous[j - 1] + (ch != hc), previous[j] + 1, current[j - 1] + 1)
        if min(current) > limit:
            return limit + 1
        previous = current
    return min(previous)


def edit_budget(normalized_needle: str) -> int:
    """How many letter slips a typed name of this length may have and still count."""
    n = len(normalized_needle)
    return 0 if n < 5 else 1 if n < 9 else 2


def find_clients(typed: str, names: Mapping[K, str]) -> list[tuple[K, str]]:
    """The clients that ``typed`` means, best kind of match first: exactly (ignoring case, spaces and punctuation), else a name containing it, else a name within a slip or two. Empty when none fits."""
    needle = normalize(typed)
    if not needle:
        return []
    named = [(key, name, normalize(name)) for key, name in names.items() if name]
    exact = [(key, name) for key, name, norm in named if norm == needle]
    if exact:
        return exact
    contained = [(key, name) for key, name, norm in named if needle in norm]
    if contained:
        return contained
    budget = edit_budget(needle)
    if budget == 0:
        return []
    return [(key, name) for key, name, norm in named if _closest_substring_distance(needle, norm, budget) <= budget]
