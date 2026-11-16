"""The customer-facing dashboard (the Rewst End User Dashboard, rebuilt): a person at a customer signs in with their own account and an authenticator app and sees ONLY their own company's tickets, hours and satisfaction.

Two sets of routes:
* ``/client-portal/summary`` for the customer (role ``client_viewer``). Which client they are is looked up from their own tenant, never taken from the request (app/services/client_portal.py).
* ``/mssp/client-portal-users`` for the MSP's staff (``mssp:manage`` and ``users:write``): create, list, reset the second factor of and turn off the customer accounts of the clients they manage. Settings > Members, Client dashboard sign-ins.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.core.account_names import InvalidAccountName, validate_account_name
from app.core.emails import normalize_email
from app.core.security import get_password_hash
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.models.responder import PasskeyCredential
from app.models.tenant import Tenant, User
from app.services import client_portal, totp_store
from app.services.account_names import account_name_taken
from app.services.audit import emit_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/client-portal", tags=["client-portal"])
admin_router = APIRouter(prefix="/mssp/client-portal-users", tags=["client-portal"])


# ----------------------------------------------------------------------------- the customer's side


async def client_portal_user(user: AuthUser, db: DBSession) -> Any:
    """The signed-in customer: role client_viewer, a session (never an API key), their own tenant, and an authenticator app set up. Anything else is refused."""
    if user.role != client_portal.CLIENT_VIEWER_ROLE or user.scopes is not None or user.viewing_other_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This page is for the client dashboard sign-in.")
    user.require_permission("client_portal:view")
    if not await totp_store.is_enabled(db, user.user_id, user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="mfa_setup_required: set up an authenticator app (Settings, Two-step sign-in) before the dashboard opens.",
        )
    return user


PortalUser = Annotated[Any, Depends(client_portal_user)]


@router.get("/summary", dependencies=[Depends(require_permission("client_portal:view"))])
async def portal_summary(user: PortalUser, db: DBSession, months: Annotated[int, Query(ge=1, le=12)] = 3) -> dict[str, Any]:
    """Your company's tickets, hours worked and satisfaction for the newest ``months`` months, from HaloPSA and SimpleSat as of CORE's last daily read. No parameter names a client."""
    client = await client_portal.resolve_client(db, user.tenant_id)
    return await client_portal.summary(db, client, months)


# ----------------------------------------------------------------------------- the MSP's side


class PortalUserOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    client_name: str
    account_name: str
    username: str
    email: str | None = None
    is_active: bool
    last_login: datetime | None = None
    mfa_enabled: bool


class CreatePortalUser(BaseModel):
    child_tenant_id: uuid.UUID
    account_name: str
    email: EmailStr | None = None
    username: str | None = None


class CreatedPortalUser(PortalUserOut):
    temporary_password: str  # shown once; the person is asked to change it, and must set up an authenticator app before the dashboard opens


class PortalActionDone(BaseModel):
    done: bool = True
    detail: str


async def _managed_children(db: Any, caller_tenant: uuid.UUID) -> dict[uuid.UUID, Tenant]:
    async with cross_tenant_reads(db):
        rows = (await db.execute(select(Tenant).where(Tenant.parent_tenant_id == caller_tenant))).scalars().all()
    return {t.id: t for t in rows}


async def _out(db: Any, user: User, tenant: Tenant) -> PortalUserOut:
    return PortalUserOut(
        id=user.id,
        tenant_id=user.tenant_id,
        client_name=tenant.name,
        account_name=user.account_name,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        last_login=user.last_login,
        mfa_enabled=await totp_store.is_enabled(db, user.id, user.tenant_id),
    )


async def _portal_user_of(db: Any, current: Any, user_id: uuid.UUID) -> tuple[User, Tenant]:
    """A client_viewer account of a client this caller manages; 404 for anything else (another MSP's customer, a staff account, an unknown id)."""
    children = await _managed_children(db, current.tenant_id)
    async with cross_tenant_reads(db):
        user = (
            await db.execute(
                select(User).where(User.id == user_id, User.role == client_portal.CLIENT_VIEWER_ROLE, User.tenant_id.in_(list(children)))
            )
        ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such client dashboard sign-in.")
    return user, children[user.tenant_id]


async def _audit(db: Any, current: Any, action: str, user_id: uuid.UUID, changes: dict[str, Any]) -> None:
    await emit_audit(
        db=db,
        tenant_id=current.tenant_id,
        actor_id=current.user_id,
        actor_email=getattr(current, "email", None),
        action=action,
        resource="client_portal_user",
        resource_id=str(user_id),
        changes=changes,
    )


@admin_router.get(
    "",
    response_model=list[PortalUserOut],
    dependencies=[Depends(require_permission("mssp:manage")), Depends(require_permission("users:write"))],
)
async def list_portal_users(current: AuthUser, db: DBSession) -> list[PortalUserOut]:
    """Every client dashboard sign-in of the clients you manage, with whether each has set up an authenticator app."""
    children = await _managed_children(db, current.tenant_id)
    if not children:
        return []
    async with cross_tenant_reads(db):
        users = (
            (
                await db.execute(
                    select(User)
                    .where(User.role == client_portal.CLIENT_VIEWER_ROLE, User.tenant_id.in_(list(children)))
                    .order_by(User.account_name)
                )
            )
            .scalars()
            .all()
        )
    return [await _out(db, u, children[u.tenant_id]) for u in users]


@admin_router.post(
    "",
    response_model=CreatedPortalUser,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("mssp:manage")), Depends(require_permission("users:write"))],
)
async def create_portal_user(body: CreatePortalUser, current: AuthUser, db: DBSession) -> CreatedPortalUser:
    """Create a client dashboard sign-in for one of your clients. The client must already be linked to a HaloPSA client (Settings, Clients). A temporary password is made and shown once; give it to the person another way."""
    children = await _managed_children(db, current.tenant_id)
    child = children.get(body.child_tenant_id)
    if child is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That client is not one of yours.")
    await client_portal.resolve_client(db, child.id)  # 409 with the reason when the client has no (or more than one) HaloPSA link
    try:
        name = validate_account_name(body.account_name)
    except InvalidAccountName as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    if await account_name_taken(db, name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That account name is already taken. Choose another.")
    email = normalize_email(body.email) if body.email else None
    if email is not None:
        taken = (await db.execute(select(User.id).where(func.lower(User.email) == email).limit(1))).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This email address cannot be used. Choose a different one.")
    password = secrets.token_urlsafe(15)
    user = User(
        id=uuid.uuid4(),
        tenant_id=child.id,
        email=email,
        account_name=name,
        username=(body.username or name).strip()[:100] or name,
        hashed_password=get_password_hash(password),
        role=client_portal.CLIENT_VIEWER_ROLE,
    )
    async with acting_as_tenant(db, child.id):
        db.add(user)
        await db.flush()
    await _audit(db, current, "client_portal_user:created", user.id, {"account_name": name, "client": child.name})
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That account name (or email) was just taken. Choose another."
        ) from None
    out = await _out(db, user, child)
    return CreatedPortalUser(**out.model_dump(), temporary_password=password)


@admin_router.post(
    "/{user_id}/reset-mfa",
    response_model=PortalActionDone,
    dependencies=[Depends(require_permission("mssp:manage")), Depends(require_permission("users:write"))],
)
async def reset_portal_user_mfa(user_id: uuid.UUID, current: AuthUser, db: DBSession) -> PortalActionDone:
    """Remove the person's authenticator app and passkeys (a lost phone) and end their sessions. The dashboard stays closed to them until they set up a new authenticator app."""
    from app.core.token_revocation import RevocationUnavailable, sign_out_everywhere  # noqa: PLC0415

    user, child = await _portal_user_of(db, current, user_id)
    async with acting_as_tenant(db, user.tenant_id):
        await db.execute(
            update(PasskeyCredential)
            .where(
                PasskeyCredential.user_id == user.id, PasskeyCredential.tenant_id == user.tenant_id, PasskeyCredential.revoked_at.is_(None)
            )
            .values(revoked_at=datetime.now(UTC))
        )
    removed = await totp_store.remove(db, user.id, user.tenant_id)
    await _audit(db, current, "client_portal_user:mfa_reset", user.id, {"account_name": user.account_name, "totp_removed": removed})
    await db.commit()
    try:
        await sign_out_everywhere(user.id)
    except RevocationUnavailable:
        return PortalActionDone(detail="Second factor removed, but their sessions could not be ended right now. Try again shortly.")
    return PortalActionDone(
        detail="Second factor removed and their sessions ended. They must set up a new authenticator app before the dashboard opens."
    )


@admin_router.delete(
    "/{user_id}",
    response_model=PortalActionDone,
    dependencies=[Depends(require_permission("mssp:manage")), Depends(require_permission("users:write"))],
)
async def turn_off_portal_user(user_id: uuid.UUID, current: AuthUser, db: DBSession) -> PortalActionDone:
    """Turn the sign-in off (the account is kept, inactive) and end its sessions."""
    from app.core.token_revocation import RevocationUnavailable, sign_out_everywhere  # noqa: PLC0415

    user, child = await _portal_user_of(db, current, user_id)
    async with acting_as_tenant(db, user.tenant_id):
        await db.execute(update(User).where(User.id == user.id).values(is_active=False, updated_at=datetime.now(UTC)))
    await _audit(db, current, "client_portal_user:turned_off", user.id, {"account_name": user.account_name, "client": child.name})
    await db.commit()
    try:
        await sign_out_everywhere(user.id)
    except RevocationUnavailable:
        return PortalActionDone(detail="Turned off, but existing sessions could not be ended right now. Try again shortly.")
    return PortalActionDone(detail="Turned off and signed out.")
