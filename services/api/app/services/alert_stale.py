"""Stale alerts: set aside for review, never deleted.

An open alert nobody has touched for ``ALERT_STALE_DAYS`` is moved to the status ``stale``: it leaves the open counts and the default lists but stays in the database, shown under the Stale filter where
it can be restored (back to the status it had) or closed in bulk. Critical and high alerts are exempt (``ALERT_STALE_EXEMPT_SEVERITIES``), so is any alert that belongs to a case, and so is one an analyst
already claimed (status ``in_progress``/``investigating``): someone is on it. Restoring touches the alert's last-updated time, so it is not set aside again the next hour.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.models.alert import Alert
from app.services.alert_status import STALE

# Only an alert nobody has started on can go stale.
CANDIDATE_STATUSES: tuple[str, ...] = ("new", "triaging")
MAX_PER_PASS = 5000


def exempt_severities(raw: str | None) -> tuple[str, ...]:
    return tuple(s for s in (part.strip().lower() for part in (raw or "").split(",")) if s)


def stale_conditions(now: datetime, days: int, exempt: Iterable[str], skip_tenants: Iterable[uuid.UUID] = ()) -> list[Any]:
    """The test an alert must pass to be set aside, as SQL conditions (also used by the summary, so the count and the sweep can never differ)."""
    skip = tuple(skip_tenants)
    return [
        *([Alert.tenant_id.notin_(skip)] if skip else []),
        Alert.status.in_(CANDIDATE_STATUSES),
        Alert.updated_at < now - timedelta(days=days),
        Alert.case_id.is_(None),
        Alert.severity.notin_(tuple(exempt)) if exempt else Alert.severity.isnot(None),
    ]


async def exempt_tenant_ids(db: Any) -> list[uuid.UUID]:
    """The clients whose alerts are never set aside (the owner switched it on for them). Read from the tenants' settings; a handful of rows, so it is filtered here, not in SQL."""
    from app.models.tenant import Tenant
    from app.services.client_mapping import tenant_stale_exempt

    rows = (await db.execute(select(Tenant))).scalars().all()
    return [t.id for t in rows if tenant_stale_exempt(t)]


async def sweep_stale(db: Any, days: int, exempt: Iterable[str], now: datetime | None = None, skip_tenants: Iterable[uuid.UUID] = ()) -> int:
    """Set aside every alert that has been quiet for ``days``. Returns how many. ``days`` of 0 or less does nothing. The caller owns the transaction."""
    if days <= 0:
        return 0
    now = now or datetime.now(UTC)
    ids = (await db.execute(select(Alert.id).where(*stale_conditions(now, days, exempt, skip_tenants)).limit(MAX_PER_PASS))).scalars().all()
    if not ids:
        return 0
    # onupdate would stamp updated_at with now; the alert's own last-touched time is what "quiet since" means, so it is kept.
    result = await db.execute(
        update(Alert)
        .where(Alert.id.in_(ids), *stale_conditions(now, days, exempt, skip_tenants))
        .values(status=STALE, status_before_stale=Alert.status, stale_at=now, updated_at=Alert.updated_at)
    )
    return int(result.rowcount or 0)


async def restore_stale(db: Any, tenant_ids: list[uuid.UUID], alert_ids: list[uuid.UUID] | None, now: datetime | None = None) -> int:
    """Put stale alerts back as they were (and as just touched). ``alert_ids`` None means every stale alert of the given clients."""
    now = now or datetime.now(UTC)
    where = [Alert.tenant_id.in_(tenant_ids), Alert.status == STALE]
    if alert_ids is not None:
        where.append(Alert.id.in_(alert_ids))
    result = await db.execute(update(Alert).where(*where).values(status=_before(), status_before_stale=None, stale_at=None, updated_at=now))
    return int(result.rowcount or 0)


async def close_stale(db: Any, tenant_ids: list[uuid.UUID], alert_ids: list[uuid.UUID] | None, now: datetime | None = None) -> int:
    """Close stale alerts for good (status closed, resolved now)."""
    now = now or datetime.now(UTC)
    where = [Alert.tenant_id.in_(tenant_ids), Alert.status == STALE]
    if alert_ids is not None:
        where.append(Alert.id.in_(alert_ids))
    result = await db.execute(update(Alert).where(*where).values(status="closed", resolved_at=now, updated_at=now))
    return int(result.rowcount or 0)


def _before() -> Any:
    from sqlalchemy import func  # noqa: PLC0415

    return func.coalesce(Alert.status_before_stale, "new")
