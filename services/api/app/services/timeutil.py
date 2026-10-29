"""One answer to "is this moment timezone-aware?".

A time that arrives without a zone (a JSON date with no offset, a SQLite or older row) is read as UTC. The check was written inline in a dozen places, and a few were missing it: a ticket's "updated" time was stored as it came, so a naive value met an aware one the first time the two were compared.
"""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(moment: datetime) -> datetime:
    """The moment with a zone: one that has none is taken to be UTC, one that has one is left as it is."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def as_utc_or_none(moment: datetime | None) -> datetime | None:
    return None if moment is None else as_utc(moment)
