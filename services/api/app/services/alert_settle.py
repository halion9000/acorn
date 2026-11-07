"""When an alert may be closed for good: its tool has closed it AND every HaloPSA ticket on it is closed.

A tool closing an incident used to resolve the alert whatever its tickets said. Now a ticket still open keeps the alert open (with a note that the tool closed it), and the alert closes when its last ticket does.
An alert whose tool has NOT closed it is never closed by its tickets: it is only flagged on the alert page ("ticket closed, still open in <tool>").

The checks are SQL conditions on ``enrichment_data`` (``tickets`` from CORE and ``manual_tickets`` by hand), so they run inside the same UPDATE that closes the alert.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, literal_column

# A ticket whose status text starts with one of these is closed (the same words as the alert page). A status that is something else is open and keeps the alert open; a ticket with NO status text (one entered by hand
# or opened by a rule, which CORE has not read a status for) neither keeps it open nor counts as closed.
CLOSED_WORDS = "closed|resolved|completed|cancel+ed|done"
_ARRAY = "case when jsonb_typeof(alerts.enrichment_data->'{k}') = 'array' then alerts.enrichment_data->'{k}' else '[]'::jsonb end"
TICKETS_SQL = f"({_ARRAY.format(k='tickets')} || {_ARRAY.format(k='manual_tickets')})"


def has_open_ticket() -> Any:
    """SQL: at least one linked ticket with a status that is not a closed one."""
    return literal_column(
        f"exists (select 1 from jsonb_array_elements({TICKETS_SQL}) t where coalesce(t->>'status', '') <> '' and t->>'status' !~* '^({CLOSED_WORDS})[[:>:]]')"
    )


def has_closed_ticket() -> Any:
    return literal_column(f"exists (select 1 from jsonb_array_elements({TICKETS_SQL}) t where t->>'status' ~* '^({CLOSED_WORDS})[[:>:]]')")


def tickets_all_closed() -> Any:
    """SQL: at least one ticket is closed and none is open."""
    return and_(has_closed_ticket(), ~has_open_ticket())


def closed_in_tool() -> Any:
    """SQL: the tool's closure was recorded on the alert (``enrichment_data.closed_in_vendor``)."""
    return literal_column("jsonb_exists(alerts.enrichment_data, 'closed_in_vendor')")
