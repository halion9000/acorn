"""Start an access review: snapshot the people of a system and open the review. Shared by the Start button and the scheduler, so both take the same snapshot."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select

from app.models.access_review import AccessReview, AccessReviewEntry
from app.models.identity_source import IdentitySource
from app.models.signin import IdentityMfaUser
from app.services import access_reviews as rules
from app.services import compliance_audit as audit

M365 = "Microsoft 365"


async def snapshot_lines(db: Any, tenant: uuid.UUID, system: str, people: list[str] | None = None) -> list[dict]:
    """The people to review for ``system``: the Microsoft 365 people held, the names given, or the people another tool reported. Empty when there is nobody."""
    if system == M365:
        users = (await db.execute(select(IdentityMfaUser).where(IdentityMfaUser.tenant_id == tenant))).scalars().all()
        return rules.entries_from_mfa_users(list(users))
    if people:
        return rules.entries_from_names(people, system)
    rows = (
        (await db.execute(select(IdentitySource).where(IdentitySource.tenant_id == tenant, IdentitySource.vendor == system)))
        .scalars()
        .all()
    )
    return rules.entries_from_identities(list(rows), system)


async def create_review(
    db: Any,
    tenant: uuid.UUID,
    *,
    name: str,
    system: str,
    reviewer: str | None,
    due_date: date | None,
    created_by: str | None,
    lines: list[dict],
    user: Any = None,
) -> AccessReview:
    """Add the review and one entry per person, and audit it. The caller commits."""
    review = AccessReview(
        id=uuid.uuid4(), tenant_id=tenant, name=name, system=system, reviewer=reviewer, due_date=due_date, created_by=created_by
    )
    db.add(review)
    await db.flush()
    for ln in lines:
        db.add(
            AccessReviewEntry(
                id=uuid.uuid4(),
                tenant_id=tenant,
                review_id=review.id,
                person=ln["person"],
                name=ln["name"],
                access=ln["access"],
                flags=ln["flags"],
            )
        )
    await audit.note(
        db, tenant, user, "access_review:started", "access_review", review.id, name=review.name, system=review.system, people=len(lines)
    )
    return review
