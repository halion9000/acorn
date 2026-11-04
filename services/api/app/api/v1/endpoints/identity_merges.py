"""Merging people on the Identities page by hand, and saying two addresses are not the same person.

The automatic rules (identity_merge.py) join the obvious pairs. These two routes are the owner's word on the rest: ``POST /identities/merges`` says two addresses are one person, and
``POST /identities/merges/separate`` says an address does NOT belong with another, which also stops any automatic rule from joining them again. A decision is kept per client by address, so it survives
every refresh of the tools' lists. Both need ``alerts:write``; both are written to the audit log.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints.devices import _as, _scope
from app.api.v1.endpoints.identities import _people
from app.models.identity_merge import IdentityMerge
from app.services.audit import emit_audit
from app.services.identity_people import normalize_email

router = APIRouter(prefix="/identities/merges", tags=["identities"])


class MergeBody(BaseModel):
    client_id: uuid.UUID
    email: str = Field(max_length=320, description="Any address of the first person.")
    with_email: str = Field(max_length=320, description="Any address of the second person.")


class SeparateBody(BaseModel):
    client_id: uuid.UUID
    email: str = Field(max_length=320, description="The address that does not belong.")
    from_email: str = Field(max_length=320, description="The address (or the person's shown address) it was joined to.")


class MergeResult(BaseModel):
    kind: Literal["merge", "separate"]
    email: str
    other: str


def ordered(a: str, b: str) -> tuple[str, str]:
    """The pair, sorted: a decision exists once whichever address was clicked first."""
    return (a, b) if a < b else (b, a)


def address_of(raw: str) -> str:
    email = normalize_email(raw)
    if email is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That is not an e-mail address.")
    return email


async def record(db, *, client: uuid.UUID, a: str, b: str, kind: str, actor: uuid.UUID | None) -> None:
    """Store one decision for the pair, replacing the opposite one. The caller owns the transaction."""
    x, y = ordered(a, b)
    await db.execute(delete(IdentityMerge).where(IdentityMerge.tenant_id == client, IdentityMerge.address_a == x, IdentityMerge.address_b == y))
    db.add(IdentityMerge(tenant_id=client, address_a=x, address_b=y, kind=kind, created_by=actor))
    await db.flush()


@router.post("", response_model=MergeResult, status_code=status.HTTP_201_CREATED)
async def merge_people_by_hand(
    body: MergeBody, request: Request, user: Annotated[AuthUser, Depends(require_permission("alerts:write"))], db: DBSession
) -> MergeResult:
    a, b = address_of(body.email), address_of(body.with_email)
    owner = user.tenant_id
    await _scope(db, owner, body.client_id)
    people, _ = await _people(db, owner, body.client_id)
    mine = [p for p in people if p.tenant_id == body.client_id]
    first = next((p for p in mine if a in p.addresses), None)
    second = next((p for p in mine if b in p.addresses), None)
    if first is None or second is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One of those people is not known for this client.")
    if first is second:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="They are already one person.")
    async with _as(db, owner, body.client_id):
        # Joining the two groups: the pair's own addresses, whichever ones were named.
        await record(db, client=body.client_id, a=first.email, b=second.email, kind="merge", actor=user.user_id)
        await emit_audit(
            db=db,
            tenant_id=body.client_id,
            actor_id=user.user_id,
            action="identities:merged",
            resource="identity",
            resource_id=first.email,
            changes={"address": first.email, "with": second.email},
            request=request,
        )
        await db.commit()
    return MergeResult(kind="merge", email=first.email, other=second.email)


@router.post("/separate", response_model=MergeResult, status_code=status.HTTP_201_CREATED)
async def say_not_the_same_person(
    body: SeparateBody, request: Request, user: Annotated[AuthUser, Depends(require_permission("alerts:write"))], db: DBSession
) -> MergeResult:
    a, b = address_of(body.email), address_of(body.from_email)
    if a == b:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Those are the same address.")
    owner = user.tenant_id
    await _scope(db, owner, body.client_id)
    async with _as(db, owner, body.client_id):
        # Every pair that ties this address to the other person's addresses is replaced by "separate": a hand merge is undone, and an automatic rule can no longer join them.
        people, _ = await _people(db, owner, body.client_id)
        group = next((p for p in people if p.tenant_id == body.client_id and a in p.addresses and b in p.addresses), None)
        others = [x for x in (group.addresses if group else [b]) if x != a]
        for other in others:
            await record(db, client=body.client_id, a=a, b=other, kind="separate", actor=user.user_id)
        await emit_audit(
            db=db,
            tenant_id=body.client_id,
            actor_id=user.user_id,
            action="identities:separated",
            resource="identity",
            resource_id=a,
            changes={"address": a, "not_with": others},
            request=request,
        )
        await db.commit()
    return MergeResult(kind="separate", email=a, other=b)
