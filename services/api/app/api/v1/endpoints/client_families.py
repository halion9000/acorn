"""Client families (roadmap huntress-family): a parent company and its linked child clients, such as New Waterloo and its "NW - " clients.

Read with ``mssp:read``, change with ``mssp:manage``. A family only links clients: every client keeps its own devices, alerts and numbers, and nothing is moved or merged. The link is what lets a record
that belongs to the group (a machine the tools file under a sibling client) be recognized as the same family's, and what lets a page show one client or the whole family.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.models.client_family import ClientFamily, ClientFamilyMember
from app.models.tenant import Tenant
from app.services import client_families as cf

router = APIRouter(prefix="/mssp/families", tags=["mssp"])

MAX_FAMILIES = 200


class FamilyIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    client_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class FamilyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    client_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)


class FamilyOut(BaseModel):
    id: uuid.UUID
    name: str
    client_ids: list[uuid.UUID]
    clients: list[str]


async def _clients(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, str]:
    return {r.id: r.name for r in (await db.execute(select(Tenant.id, Tenant.name).where(Tenant.parent_tenant_id == owner))).all()}


async def load_family_map(db: Any, owner: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    """``client -> family`` for the owner's clients."""
    rows = (await db.execute(select(ClientFamilyMember.family_id, ClientFamilyMember.client_tenant_id).where(ClientFamilyMember.tenant_id == owner))).all()
    return cf.family_map([(r[0], r[1]) for r in rows])


async def _listing(db: Any, owner: uuid.UUID) -> list[FamilyOut]:
    names = await _clients(db, owner)
    families = (await db.execute(select(ClientFamily).where(ClientFamily.tenant_id == owner).order_by(ClientFamily.name))).scalars().all()
    fmap = await load_family_map(db, owner)
    out = []
    for f in families:
        ids = [c for c, fam in fmap.items() if fam == f.id and c in names]
        ids.sort(key=lambda c: names[c].lower())
        out.append(FamilyOut(id=f.id, name=f.name, client_ids=ids, clients=[names[c] for c in ids]))
    return out


async def _save_members(db: Any, owner: uuid.UUID, family_id: uuid.UUID, client_ids: list[uuid.UUID]) -> None:
    names = await _clients(db, owner)
    members, problem = cf.clean_members(client_ids, set(names), await load_family_map(db, owner), family_id)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    await db.execute(delete(ClientFamilyMember).where(ClientFamilyMember.tenant_id == owner, ClientFamilyMember.family_id == family_id))
    for c in members:
        db.add(ClientFamilyMember(tenant_id=owner, family_id=family_id, client_tenant_id=c))


@router.get("", response_model=list[FamilyOut], summary="The client families")
async def list_families(user: Annotated[AuthUser, Depends(require_permission("mssp:read"))], db: DBSession) -> list[FamilyOut]:
    return await _listing(db, user.tenant_id)


@router.post("", response_model=FamilyOut, status_code=status.HTTP_201_CREATED, summary="Create a family from a name and its clients")
async def create_family(body: FamilyIn, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> FamilyOut:
    owner = user.tenant_id
    existing = (await db.execute(select(ClientFamily).where(ClientFamily.tenant_id == owner))).scalars().all()
    if len(existing) >= MAX_FAMILIES:
        raise HTTPException(status_code=400, detail="That is the most families there can be.")
    if any(f.name.strip().lower() == body.name.strip().lower() for f in existing):
        raise HTTPException(status_code=409, detail="A family with that name already exists.")
    family = ClientFamily(id=uuid.uuid4(), tenant_id=owner, name=body.name.strip(), created_by=str(user.user_id))
    db.add(family)
    await db.flush()
    await _save_members(db, owner, family.id, body.client_ids)
    await db.commit()
    return next(f for f in await _listing(db, owner) if f.id == family.id)


@router.patch("/{family_id}", response_model=FamilyOut, summary="Rename a family or replace its clients")
async def change_family(family_id: uuid.UUID, body: FamilyPatch, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> FamilyOut:
    owner = user.tenant_id
    family = (await db.execute(select(ClientFamily).where(ClientFamily.id == family_id, ClientFamily.tenant_id == owner))).scalar_one_or_none()
    if family is None:
        raise HTTPException(status_code=404, detail="That family was not found.")
    if body.name is not None:
        others = (await db.execute(select(ClientFamily).where(ClientFamily.tenant_id == owner, ClientFamily.id != family_id))).scalars().all()
        if any(f.name.strip().lower() == body.name.strip().lower() for f in others):
            raise HTTPException(status_code=409, detail="A family with that name already exists.")
        family.name = body.name.strip()
    if body.client_ids is not None:
        await _save_members(db, owner, family_id, body.client_ids)
    await db.commit()
    return next(f for f in await _listing(db, owner) if f.id == family_id)


@router.delete("/{family_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a family (its clients are not touched)")
async def delete_family(family_id: uuid.UUID, user: Annotated[AuthUser, Depends(require_permission("mssp:manage"))], db: DBSession) -> None:
    owner = user.tenant_id
    family = (await db.execute(select(ClientFamily).where(ClientFamily.id == family_id, ClientFamily.tenant_id == owner))).scalar_one_or_none()
    if family is None:
        raise HTTPException(status_code=404, detail="That family was not found.")
    await db.delete(family)
    await db.commit()
