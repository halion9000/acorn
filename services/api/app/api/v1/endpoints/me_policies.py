"""My policies: the policies assigned to the signed-in person, their text, and a way to accept them.

Seeing the list is open to everyone who can use the console (alerts:read); accepting needs reports:read (the viewer role has it, CORE's key does not) and a signed-in person, never an API key. A person sees and accepts only what is assigned to their own e-mail address, in their own organization. Accepting records the person's own
address, the version and the day; it needs the policy to be assigned to them and is the same record the compliance side reads (``policy_acceptances``). Nothing here changes a policy or who it is assigned to.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.v1.deps import AuthUser, require_permission
from app.db.rls import TenantDBSession
from app.models.governance import GovernanceItem, GovernanceVersion
from app.models.policy_acceptance import PolicyAcceptance, PolicyAssignment
from app.services import compliance_audit as audit
from app.services import policy_assignment as pas

router = APIRouter(prefix="/me/policies", tags=["compliance"])

# A policy's text is shown whole, up to this many characters (the stored limit is 100,000).
TEXT_CAP = 100_000


class MyPolicy(BaseModel):
    item_id: uuid.UUID
    title: str
    version: int
    body: str
    due_on: date
    state: str  # pending / overdue / accepted
    accepted_on: date | None


class MyPolicies(BaseModel):
    policies: list[MyPolicy]
    to_accept: int  # how many are pending or overdue


def _me(user: AuthUser) -> str:
    return (getattr(user, "email", "") or "").strip().lower()


async def _mine(db: TenantDBSession, user: AuthUser, only: uuid.UUID | None = None) -> list[MyPolicy]:
    email = _me(user)
    if not email:
        return []
    q = (
        select(PolicyAssignment, GovernanceItem)
        .join(GovernanceItem, GovernanceItem.id == PolicyAssignment.item_id)
        .where(PolicyAssignment.tenant_id == user.tenant_id, PolicyAssignment.email == email, GovernanceItem.archived_at.is_(None))
        .order_by(PolicyAssignment.due_on, GovernanceItem.title)
    )
    if only is not None:
        q = q.where(PolicyAssignment.item_id == only)
    pairs = (await db.execute(q)).all()
    if not pairs:
        return []
    item_ids = [i.id for _, i in pairs]
    newest = dict(
        (
            await db.execute(
                select(GovernanceVersion.item_id, func.max(GovernanceVersion.version))
                .where(GovernanceVersion.item_id.in_(item_ids))
                .group_by(GovernanceVersion.item_id)
            )
        ).all()
    )
    bodies = {
        (v.item_id, v.version): v.body
        for v in (await db.execute(select(GovernanceVersion).where(GovernanceVersion.item_id.in_(item_ids)))).scalars()
        if newest.get(v.item_id) == v.version
    }
    accepted = {
        (a.item_id, a.version): a.accepted_on
        for a in (
            await db.execute(select(PolicyAcceptance).where(PolicyAcceptance.item_id.in_(item_ids), PolicyAcceptance.email == email))
        ).scalars()
    }
    today = datetime.now(UTC).date()
    out: list[MyPolicy] = []
    for assignment, item in pairs:
        version = newest.get(item.id)
        if version is None:
            continue  # nothing written yet, so nothing to read or accept
        when = accepted.get((item.id, version))
        out.append(
            MyPolicy(
                item_id=item.id,
                title=item.title,
                version=version,
                body=bodies.get((item.id, version), "")[:TEXT_CAP],
                due_on=assignment.due_on,
                state=pas.state_of(assignment.due_on, when is not None, today),
                accepted_on=when,
            )
        )
    return out


@router.get(
    "", response_model=MyPolicies, summary="The policies assigned to me, with their text and whether I have accepted the newest version"
)
async def my_policies(user: Annotated[AuthUser, Depends(require_permission("alerts:read"))], db: TenantDBSession) -> MyPolicies:
    rows = await _mine(db, user)
    return MyPolicies(policies=rows, to_accept=sum(1 for r in rows if r.state != "accepted"))


@router.post("/{item_id}/accept", response_model=MyPolicy, summary="Accept the newest version of a policy assigned to me")
async def accept_policy(
    item_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("reports:read"))], db: TenantDBSession
) -> MyPolicy:
    # Accepting is a person's own act: an API key (CORE's, an agent's) never accepts on anyone's behalf, even if it were given the permission.
    if getattr(user, "scopes", None) is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A policy is accepted by the signed-in person, not by an API key.")
    mine = await _mine(db, user, only=item_id)
    if not mine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That policy is not assigned to you.")
    current = mine[0]
    if current.state == "accepted":
        return current
    email = _me(user)
    today = datetime.now(UTC).date()
    db.add(
        PolicyAcceptance(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            item_id=item_id,
            version=current.version,
            email=email,
            display_name=None,
            accepted_on=today,
            recorded_by=email,
        )
    )
    await audit.note(db, user.tenant_id, user, "policy_acceptance:self", "governance_item", item_id, version=current.version)
    await db.commit()
    return (await _mine(db, user, only=item_id))[0]
