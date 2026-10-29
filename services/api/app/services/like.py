"""Escaping what a person typed before it goes into a SQL ``LIKE``.

``%`` and ``_`` are wildcards, so a search for ``50%`` or ``a_b`` matched far more than it said (and ``%`` alone matched everything). The alerts search escaped them; the audit log filters did not.
"""

from __future__ import annotations

ESCAPE = "\\"


def escape_like(value: str) -> str:
    """The text with the escape character, ``%`` and ``_`` escaped; use it with ``like(..., escape=ESCAPE)`` or ``ilike(..., escape=ESCAPE)``."""
    return value.replace(ESCAPE, ESCAPE * 2).replace("%", ESCAPE + "%").replace("_", ESCAPE + "_")
