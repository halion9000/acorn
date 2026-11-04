"""Licence waste: licences a client pays for that nobody has been given.

Each tool that sells licences reports how many are bought (``count``) and how many are not assigned to anyone (``available``). The gap is the waste: a quantity to hand back or reassign, shown as a number and
a share, never as money (prices are not held here). A count that has not been refreshed for a while is marked stale, so an old number is not read as today's.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

STALE_AFTER = timedelta(days=7)


@dataclass
class WasteRow:
    client_id: uuid.UUID
    client_name: str
    source: str
    item: str
    bought: int
    unassigned: int
    percent: int
    stale: bool


def waste_rows(counts: list[Any], names: dict[uuid.UUID, str], now: datetime, minimum: int = 1) -> list[WasteRow]:
    """The licences with at least ``minimum`` unassigned, most unassigned first. A row with no ``available`` (the tool did not say) is left out: not knowing is not zero waste, and not waste either."""
    out: list[WasteRow] = []
    for c in counts:
        if c.unit != "licence" or c.available is None or c.count <= 0 or c.available < minimum:
            continue
        unassigned = min(int(c.available), int(c.count))
        updated = c.updated_at if c.updated_at.tzinfo else c.updated_at.replace(tzinfo=now.tzinfo)
        out.append(
            WasteRow(
                client_id=c.tenant_id,
                client_name=names.get(c.tenant_id) or str(c.tenant_id),
                source=c.source,
                item=c.item,
                bought=int(c.count),
                unassigned=unassigned,
                percent=round(100 * unassigned / int(c.count)),
                stale=now - updated > STALE_AFTER,
            )
        )
    return sorted(out, key=lambda r: (-r.unassigned, r.client_name.lower(), r.item))
