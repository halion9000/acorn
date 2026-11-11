"""Tenant and user management endpoints."""

import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.core.account_names import InvalidAccountName, validate_account_name
from app.core.emails import normalize_email
from app.core.security import get_password_hash
from app.db.rls_scope import acting_as_argument
from app.models.tenant import Tenant, User
from app.models.tenant_access import ACCESS_VIEW, TenantAccessGrant
from app.services.account_names import account_name_taken, unique_account_name
from app.services.audit import emit_audit
from app.services.tenant_selection import CROSS_TENANT_PERMISSION, selectable_tenants
from app.services.user_lookup import find_user_by_account_name
from app.services.view_as import home_tenant_of, may_manage_access, viewable_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])


class TenantHeaderResponse(BaseModel):
    """Minimal tenant identity payload — safe for *any* authenticated user.

    Used by the SOC console TopBar to render the tenant switcher and role
    badge (Workstream 5). Intentionally excludes `plan`, `settings`, and
    `limits` so it does not leak privileged config to viewer/analyst roles.
    """

    id: uuid.UUID
    name: str
    mssp_role: str | None
    parent_tenant_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    settings: dict
    limits: dict
    mssp_role: str | None = None
    parent_tenant_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomRoleRef(BaseModel):
    id: uuid.UUID
    name: str


class UserResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str | None = None
    account_name: str
    username: str
    role: str
    is_active: bool
    last_login: datetime | None
    created_at: datetime
    # Roles the workspace made itself, held in addition to the built-in role above (their permissions add up). Filled by the member routes.
    custom_roles: list[CustomRoleRef] = []
    # Second factors this person has set up: how many passkeys, and whether the authenticator app is confirmed. Filled only by the members list; a count and a yes/no, never a key or secret.
    passkeys: int = 0
    authenticator: bool = False

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    """`account_name` is what the person signs in with (3-32 lower-case letters, digits, '.', '_', '-'; unique across the platform). If it is left out (an older client) one is made from `username`, or from the email, and made unique.
    `email` is optional contact information: it is not verified and not needed to sign in. `username` is a display name and defaults to the account name."""

    account_name: str | None = None
    email: EmailStr | None = None
    username: str | None = None
    password: str
    role: str = "soc_analyst"
    custom_role_ids: list[uuid.UUID] = []

    @model_validator(mode="after")
    def _needs_a_name(self) -> "CreateUserRequest":
        if not (self.account_name or self.username or self.email):
            raise ValueError("give an account_name (or a username or email to make one from)")
        return self


class UpdateUserRequest(BaseModel):
    username: str | None = None
    role: str | None = None
    is_active: bool | None = None
    # The whole set of custom roles the person should hold (replaces what they have). Left out: unchanged.
    custom_role_ids: list[uuid.UUID] | None = None


class UpdateTenantSettingsRequest(BaseModel):
    settings: dict = {}


class RenameWorkspaceRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not 2 <= len(cleaned) <= 80:
            raise ValueError("Use 2 to 80 characters.")
        if any(ch in cleaned for ch in "<>\x00"):
            raise ValueError("Leave out < and >.")
        return cleaned


class SelectableTenant(BaseModel):
    """Just enough to label a picker entry: the same minimal identity as /me/identity (no plan, settings or limits)."""

    id: uuid.UUID
    name: str
    slug: str


class SelectableTenantsResponse(BaseModel):
    own_tenant_id: uuid.UUID
    can_select_other_tenants: bool
    tenants: list[SelectableTenant]


@router.get("/selectable", response_model=SelectableTenantsResponse)
async def list_selectable_tenants(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
) -> SelectableTenantsResponse:
    """The tenants this caller may choose between in a tenant picker.

    Your own tenant, plus every other tenant if (and only if) you hold platform:cross_tenant_query; anyone else gets exactly one entry, their own, and `can_select_other_tenants: false`. Needs alerts:read (every role holds it), the permission of the pages that offer a picker."""
    can, rows = await selectable_tenants(db, current_user)
    return SelectableTenantsResponse(
        own_tenant_id=current_user.tenant_id,
        can_select_other_tenants=can,
        tenants=[SelectableTenant(id=t.id, name=t.name, slug=t.slug) for t in rows],
    )


class ViewableTenant(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    # self: the caller's own tenant. granted: a tenant the caller has been granted (read-only). platform: any tenant, for a holder of the cross-tenant permission.
    relationship: Literal["self", "platform", "granted"]
    # What they may do there: view (read-only) or full (read and write as their own role allows; identity administration excepted). Always full for their own tenant.
    access: Literal["view", "full"] = "view"


class ViewableTenantsResponse(BaseModel):
    home_tenant_id: uuid.UUID
    tenants: list[ViewableTenant]


@router.get("/viewable", response_model=ViewableTenantsResponse)
async def list_viewable_tenants(
    current_user: Annotated[AuthUser, Depends(require_permission("alerts:read"))],
    db: DBSession,
) -> ViewableTenantsResponse:
    """The tenants this caller may VIEW (read-only) with the `X-View-As-Tenant` header: their own first, then the tenants they were GRANTED (read-only; see `PUT /tenants/{id}/access/{account_name}`) or every tenant (a platform admin).

    It is the same rule the server applies when the header is sent (app.services.view_as), so the console can only offer what will be honoured. It always answers for the person's own account, whatever is being viewed.
    """
    rows = await viewable_access(db, current_user)
    return ViewableTenantsResponse(
        home_tenant_id=home_tenant_of(current_user),
        tenants=[ViewableTenant(id=t.id, name=t.name, slug=t.slug, relationship=rel, access=access) for t, rel, access in rows],
    )


class ManageableTenant(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    # self: the caller's own tenant. child: a tenant whose parent is the caller's. other: any other tenant, for a platform admin.
    relationship: Literal["self", "child", "other"]


class ManageableTenantsResponse(BaseModel):
    home_tenant_id: uuid.UUID
    tenants: list[ManageableTenant]


@router.get("/manageable", response_model=ManageableTenantsResponse)
async def list_manageable_tenants(
    current_user: Annotated[AuthUser, Depends(require_permission("users:read"))],
    db: DBSession,
) -> ManageableTenantsResponse:
    """The tenants whose ACCESS this caller may manage (who may be granted a view of them): the tenants for which `PUT /tenants/{id}/access/{account_name}` would be allowed, own tenant first. It is built from the same rule as those routes
    (`may_manage_access`), so the console can only offer what the server will honour. Empty for a role that cannot manage access."""
    home = home_tenant_of(current_user)
    query = select(Tenant).order_by(Tenant.name).limit(500)
    if not current_user.holds(CROSS_TENANT_PERMISSION):
        query = select(Tenant).where((Tenant.id == home) | (Tenant.parent_tenant_id == home)).order_by(Tenant.name).limit(500)
    candidates = (await db.execute(query)).scalars().all()
    managed = [t for t in candidates if may_manage_access(current_user, t)]
    managed.sort(key=lambda t: (t.id != home, t.name.lower()))
    return ManageableTenantsResponse(
        home_tenant_id=home,
        tenants=[
            ManageableTenant(
                id=t.id,
                name=t.name,
                slug=t.slug,
                relationship="self" if t.id == home else "child" if t.parent_tenant_id == home else "other",
            )
            for t in managed
        ],
    )


class GrantAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # `view` (the default, so a request with no body is read-only) or `full`: read and write as the person's own role allows, identity and credential administration excepted.
    access: Literal["view", "full"] = "view"


class AccessGrantResponse(BaseModel):
    tenant_id: uuid.UUID  # the tenant the access is TO
    user_id: uuid.UUID
    account_name: str
    email: str | None = None
    username: str | None = None
    home_tenant_id: uuid.UUID  # the tenant the person belongs to
    access: str
    granted_by: str
    created_at: datetime


def _grant_response(grant: TenantAccessGrant, user: User) -> AccessGrantResponse:
    return AccessGrantResponse(
        tenant_id=grant.tenant_id,
        user_id=user.id,
        account_name=user.account_name,
        email=user.email,
        username=user.username,
        home_tenant_id=user.tenant_id,
        access=grant.access,
        granted_by=grant.granted_by_label,
        created_at=grant.created_at,
    )


acting_as_tenant_in_path = acting_as_argument("tenant_id")


async def _tenant_whose_access_the_caller_manages(db: Any, current_user: Any, tenant_id: uuid.UUID) -> Tenant:
    """The tenant, if the caller may manage who has access to it; otherwise the SAME 404 as for a tenant that does not exist, so this cannot be used to find out which tenants exist."""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalars().first()
    if tenant is None or not may_manage_access(current_user, tenant):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/{tenant_id}/access", response_model=list[AccessGrantResponse])
@acting_as_tenant_in_path
async def list_tenant_access(
    tenant_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("users:read"))],
    db: DBSession,
) -> list[AccessGrantResponse]:
    """Who has been GRANTED read-only access to this tenant (people who belong to other tenants). For a platform admin, this tenant's own administrators, or the administrators of its parent."""
    tenant = await _tenant_whose_access_the_caller_manages(db, current_user, tenant_id)
    rows = (
        await db.execute(
            select(TenantAccessGrant, User)
            .join(User, User.id == TenantAccessGrant.user_id)
            .where(TenantAccessGrant.tenant_id == tenant.id)
            .order_by(User.account_name)
        )
    ).all()
    return [_grant_response(g, u) for g, u in rows]


@router.put("/{tenant_id}/access/{account_name}", response_model=AccessGrantResponse)
@acting_as_tenant_in_path
async def grant_tenant_access(
    tenant_id: uuid.UUID,
    account_name: str,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
    body: GrantAccessRequest | None = None,
) -> AccessGrantResponse:
    """Let the person with this account name work in this tenant: `view` (read-only, the default) or `full` (read and write as their own role allows; users, roles, API keys and access administration excepted). Idempotent; asking for a different level changes
    the existing grant. Takes effect on their next request. Recorded in this tenant's own audit log."""
    level = body.access if body is not None else ACCESS_VIEW
    tenant = await _tenant_whose_access_the_caller_manages(db, current_user, tenant_id)
    grantee = await find_user_by_account_name(db, account_name)
    if grantee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No account with that name")
    if grantee.tenant_id == tenant.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That account already belongs to this tenant; a grant is for people who belong to another one.",
        )
    if grantee.is_active is False:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That account is deactivated.")

    # Plain values, taken now: a rollback expires every object loaded in the session, and reading an expired one would try to do IO where it cannot.
    grantee_id, tenant_pk = grantee.id, tenant.id

    def find() -> Any:
        return select(TenantAccessGrant).where(TenantAccessGrant.user_id == grantee_id, TenantAccessGrant.tenant_id == tenant_pk)

    existing = (await db.execute(find())).scalars().first()
    if existing is not None:
        if existing.access == level:
            return _grant_response(existing, grantee)
        before, existing.access = existing.access, level
        await emit_audit(
            db=db,
            tenant_id=tenant_pk,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            action="tenant:access_changed",
            resource="tenant_access",
            resource_id=str(grantee_id),
            changes={"account_name": grantee.account_name, "home_tenant_id": str(grantee.tenant_id), "before": before, "after": level},
        )
        await db.commit()
        return _grant_response(existing, grantee)
    grant = TenantAccessGrant(
        user_id=grantee.id,
        tenant_id=tenant.id,
        access=level,
        granted_by=current_user.user_id,
        granted_by_label=current_user.email or str(current_user.user_id),
    )
    db.add(grant)
    try:
        await emit_audit(
            db=db,
            tenant_id=tenant.id,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            action="tenant:access_granted",
            resource="tenant_access",
            resource_id=str(grantee.id),
            changes={"account_name": grantee.account_name, "home_tenant_id": str(grantee.tenant_id), "access": level},
        )
        await db.commit()
    except IntegrityError:
        # Two requests granted the same person at once: the database's unique constraint decided, and this one is the "already granted" case.
        await db.rollback()
        existing = (await db.execute(find())).scalars().first()
        if existing is None:
            raise
        return _grant_response(
            existing, await find_user_by_account_name(db, account_name)
        )  # the person is read again: the rollback expired the copy loaded above
    await db.refresh(grant)
    return _grant_response(grant, grantee)


@router.delete("/{tenant_id}/access/{account_name}", status_code=status.HTTP_204_NO_CONTENT)
@acting_as_tenant_in_path
async def revoke_tenant_access(
    tenant_id: uuid.UUID,
    account_name: str,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> None:
    """Take the person's access to this tenant away. Takes effect on their next request. Recorded in this tenant's own audit log."""
    tenant = await _tenant_whose_access_the_caller_manages(db, current_user, tenant_id)
    grantee = await find_user_by_account_name(db, account_name)
    grant = None
    if grantee is not None:
        grant = (
            (
                await db.execute(
                    select(TenantAccessGrant).where(TenantAccessGrant.user_id == grantee.id, TenantAccessGrant.tenant_id == tenant.id)
                )
            )
            .scalars()
            .first()
        )
    if grantee is None or grant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such grant")
    await db.delete(grant)
    await emit_audit(
        db=db,
        tenant_id=tenant.id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action="tenant:access_revoked",
        resource="tenant_access",
        resource_id=str(grantee.id),
        changes={"account_name": grantee.account_name, "home_tenant_id": str(grantee.tenant_id)},
    )
    await db.commit()


@router.get("/me/identity", response_model=TenantHeaderResponse)
async def get_my_tenant_identity(
    current_user: AuthUser,
    db: DBSession,
) -> TenantHeaderResponse:
    """Get minimal tenant identity for the current user.

    Returns only `id`, `name`, `mssp_role`, and `parent_tenant_id`. This is
    safe for **any** authenticated user (analyst, viewer, responder, etc.)
    because it does not expose plan, settings, or limits. Used by the SOC
    console TopBar to render the tenant switcher pill and role badge.
    """
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return TenantHeaderResponse.model_validate(tenant)


@router.get("/me", response_model=TenantResponse)
async def get_my_tenant(
    current_user: Annotated[AuthUser, Depends(require_permission("settings:read"))],
    db: DBSession,
) -> TenantResponse:
    """Get the current user's tenant details (full config — requires settings:read)."""
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return TenantResponse.model_validate(tenant)


@router.patch("/me/settings", response_model=TenantResponse)
async def update_tenant_settings(
    request: UpdateTenantSettingsRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("settings:write"))],
    db: DBSession,
) -> TenantResponse:
    """Update tenant settings."""
    await db.execute(
        update(Tenant)
        .where(Tenant.id == current_user.tenant_id)
        .values(
            settings=request.settings,
            updated_at=datetime.now(UTC),
        )
    )
    await db.commit()

    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    return TenantResponse.model_validate(result.scalar_one())


@router.patch("/me/name", response_model=TenantResponse)
async def rename_my_workspace(
    request: RenameWorkspaceRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("settings:write"))],
    db: DBSession,
) -> TenantResponse:
    """Give this workspace its name (shown in Settings and the top bar). The slug and id stay as they are."""
    tenant = (await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))).scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    before = tenant.name
    if before != request.name:
        tenant.name = request.name
        tenant.updated_at = datetime.now(UTC)
        await emit_audit(
            db=db,
            tenant_id=tenant.id,
            actor_id=current_user.user_id,
            actor_email=current_user.email,
            action="tenant:renamed",
            resource="tenant",
            resource_id=str(tenant.id),
            changes={"before": before, "after": request.name},
        )
        await db.commit()
    return TenantResponse.model_validate(tenant)


async def _custom_roles_of(db: Any, tenant_id: uuid.UUID, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[CustomRoleRef]]:
    """The custom (non built-in) roles each of these people holds, by person."""
    from app.models.rbac import Role, UserRole  # noqa: PLC0415

    out: dict[uuid.UUID, list[CustomRoleRef]] = {u: [] for u in user_ids}
    if not user_ids:
        return out
    rows = (
        await db.execute(
            select(UserRole.user_id, Role.id, Role.name)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids), Role.tenant_id == tenant_id, Role.is_system.is_(False))
            .order_by(Role.name)
        )
    ).all()
    for user_id, role_id, name in rows:
        out[user_id].append(CustomRoleRef(id=role_id, name=name))
    return out


async def _user_out(db: Any, tenant_id: uuid.UUID, user: User) -> UserResponse:
    out = UserResponse.model_validate(user)
    out.custom_roles = (await _custom_roles_of(db, tenant_id, [user.id])).get(user.id, [])
    return out


async def _checked_custom_roles(db: Any, current_user: Any, role_ids: list[uuid.UUID]) -> list[Any]:
    """The roles these ids name, each of them this workspace's own role and held in full by the caller (handing a role out hands out everything in it)."""
    from app.api.v1.endpoints.rbac import _get_role_or_404, _load_role_permissions, _require_permissions_held  # noqa: PLC0415

    roles = []
    for role_id in dict.fromkeys(role_ids):
        role = await _get_role_or_404(db, role_id, current_user.tenant_id)
        _require_permissions_held(current_user, [p.name for p in await _load_role_permissions(db, role.id)])
        roles.append(role)
    return roles


_ADMIN_ROLES = ("tenant_admin", "platform_admin")


async def _one_role(db: Any, current_user: Any, role: str, role_ids: list[uuid.UUID]) -> list[Any]:
    """A person has ONE role: a built-in role, or a custom role their workspace made (stored as the role "custom" plus that one custom role). Returns the custom roles to give (one or none)."""
    if role == "custom":
        if len(set(role_ids)) != 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose exactly one custom role.")
        return await _checked_custom_roles(db, current_user, role_ids)
    if role_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A person has one role: a built-in role or a custom role, not both."
        )
    return []


async def _may_manage(db: Any, current_user: Any, user: User) -> bool:
    """May the caller change this person? Only someone whose own permissions cover everything the person's role grants (nobody manages more power than they hold)."""
    if user.role != "custom":
        return current_user.can_grant_role(user.role)
    from app.api.v1.deps import custom_role_grants  # noqa: PLC0415

    perms = await custom_role_grants(db, user) or []
    if "*" in perms and not current_user.holds_wildcard():
        return False
    return all(current_user.holds(p) for p in perms if p != "*")


async def _refuse_if_last_admin(db: Any, tenant_id: uuid.UUID, user: User, what: str) -> None:
    """409 when ``what`` (disabling, deleting or demoting) would leave the workspace with no active administrator."""
    if user.role not in _ADMIN_ROLES or not user.is_active:
        return
    others = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant_id, User.id != user.id, User.is_active.is_(True), User.role.in_(_ADMIN_ROLES))
    )
    if not others:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This is the only active administrator. {what} would lock everyone out of settings; make someone else an administrator first.",
        )


@router.get("/me/users", response_model=list[UserResponse])
async def list_users(
    current_user: Annotated[AuthUser, Depends(require_permission("users:read"))],
    db: DBSession,
) -> list[UserResponse]:
    """List all users in the current tenant."""
    result = await db.execute(select(User).where(User.tenant_id == current_user.tenant_id).order_by(User.created_at))
    users = result.scalars().all()
    roles = await _custom_roles_of(db, current_user.tenant_id, [u.id for u in users])
    passkeys, authenticator = await _second_factors_of(db, current_user.tenant_id)
    out = []
    for u in users:
        item = UserResponse.model_validate(u)
        item.custom_roles = roles.get(u.id, [])
        item.passkeys = passkeys.get(u.id, 0)
        item.authenticator = u.id in authenticator
        out.append(item)
    return out


async def _second_factors_of(db: Any, tenant_id: uuid.UUID) -> tuple[dict[uuid.UUID, int], set[uuid.UUID]]:
    """Passkey counts per person and the people with a confirmed authenticator app, in two queries for the whole workspace."""
    from app.models.responder import PasskeyCredential  # noqa: PLC0415
    from app.models.user_totp import UserTotp  # noqa: PLC0415

    counts = (
        await db.execute(
            select(PasskeyCredential.user_id, func.count())
            .where(PasskeyCredential.tenant_id == tenant_id)
            .group_by(PasskeyCredential.user_id)
        )
    ).all()
    apps = (
        (await db.execute(select(UserTotp.user_id).where(UserTotp.tenant_id == tenant_id, UserTotp.confirmed_at.is_not(None))))
        .scalars()
        .all()
    )
    return {uid: int(n) for uid, n in counts}, set(apps)


def _require_grantable_role(current_user: Any, role: str) -> None:
    """422 for a role that does not exist, 403 for one the caller may not hand out (see CurrentUser.can_grant_role)."""
    from app.core.security import ROLE_PERMISSIONS  # noqa: PLC0415

    if role not in ROLE_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown role. Known roles: {', '.join(sorted(ROLE_PERMISSIONS))}."
        )
    if not current_user.can_grant_role(role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot assign a role that grants more than your own.")


async def _audit_user(db: Any, current_user: Any, action: str, user_id: uuid.UUID, changes: dict[str, Any]) -> None:
    """Record a change to a person in the tamper-evident audit trail, with what changed (old and new role, never a password). The caller commits."""
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        actor_email=getattr(current_user, "email", None),
        action=action,
        resource="user",
        resource_id=str(user_id),
        changes=changes,
    )


@router.post("/me/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> UserResponse:
    """Create a new user in the current tenant."""
    _require_grantable_role(current_user, request.role)
    custom_roles = await _one_role(db, current_user, request.role, request.custom_role_ids)

    # The account name. Chosen explicitly: it must be valid and free (a name is not sensitive, so "taken" is said plainly). Not chosen (an older client): made from the username or email and made unique.
    if request.account_name is not None:
        try:
            name = validate_account_name(request.account_name)
        except InvalidAccountName as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
        if await account_name_taken(db, name):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That account name is already taken. Choose another.")
    else:
        name = await unique_account_name(db, request.username or request.email or "")

    # The optional email. Addresses are unique across ALL tenants, so a clash may be with a user of another organisation. Say so only for the caller's own tenant, whose users the caller can list anyway; for another
    # tenant's user do not confirm that the address is registered anywhere (that would tell this admin who uses the platform), and record the attempt so probing can be seen.
    email = (
        normalize_email(request.email) if request.email else None
    )  # stored lower-cased: `Alice@x` and `alice@x` are one address (app/core/emails.py)
    if email is not None:
        owner_tenant = (
            await db.execute(select(User.tenant_id).where(func.lower(User.email) == email).order_by(User.created_at.asc()).limit(1))
        ).scalar_one_or_none()
        if owner_tenant is not None:
            if owner_tenant == current_user.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists in your organization."
                )
            logger.warning(
                "user creation refused: the email belongs to a user of another tenant",
                extra={
                    "acting_tenant": str(current_user.tenant_id),
                    "acting_user": str(current_user.user_id),
                    "email_sha256": hashlib.sha256(email.encode()).hexdigest()[:16],
                },
            )
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This email address cannot be used. Choose a different one.")

    user = User(
        id=uuid.uuid4(),  # known now, so the audit entry below can name the new person before anything is flushed
        tenant_id=current_user.tenant_id,
        email=email,
        account_name=name,
        username=request.username or name,
        hashed_password=get_password_hash(request.password),
        role=request.role,
    )
    db.add(user)
    if custom_roles:
        from app.models.rbac import UserRole  # noqa: PLC0415

        await db.flush()
        for role in custom_roles:
            db.add(UserRole(user_id=user.id, role_id=role.id, assigned_by=current_user.user_id))
    await _audit_user(
        db,
        current_user,
        "user:created",
        user.id,
        {"account_name": name, "role": request.role, "custom_roles": [r.name for r in custom_roles]},
    )
    try:
        await db.commit()
    except IntegrityError:
        # Two requests took the same name (or email) at once: the database's unique index decided.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That account name (or email) was just taken. Choose another."
        ) from None
    await db.refresh(user)
    out = UserResponse.model_validate(user)
    out.custom_roles = [CustomRoleRef(id=r.id, name=r.name) for r in custom_roles]  # a new person holds exactly the roles just given
    return out


@router.patch("/me/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    request: UpdateUserRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> UserResponse:
    """Update a user."""
    result = await db.execute(select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Nobody edits a user who holds more power than they do (a tenant_admin could otherwise deactivate or demote a platform_admin of the same tenant), and
    # nobody changes their OWN role (a tenant_admin could otherwise promote itself with one request).
    if not await _may_manage(db, current_user, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot modify a user whose role grants more than your own.")
    if request.role is not None:
        if user.id == current_user.user_id and request.role != user.role:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot change your own role.")
        _require_grantable_role(current_user, request.role)
        if request.role != user.role and request.role not in _ADMIN_ROLES:
            await _refuse_if_last_admin(db, current_user.tenant_id, user, "Changing this role")
    if request.is_active is False:
        if user.id == current_user.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot disable your own account.")
        await _refuse_if_last_admin(db, current_user.tenant_id, user, "Disabling this account")
    # One role per person. Becoming a custom-role person needs exactly one custom role; any built-in role clears custom roles; staying custom without naming one leaves it as it is.
    final_role = request.role if request.role is not None else user.role
    new_custom: list[Any] | None = None
    if final_role == "custom":
        if request.custom_role_ids is not None:
            new_custom = await _one_role(db, current_user, "custom", request.custom_role_ids)
        elif user.role != "custom":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose which custom role this person gets.")
    else:
        await _one_role(db, current_user, final_role, request.custom_role_ids or [])  # refuses a custom role next to a built-in one
        # Custom roles are cleared when the person stops being a custom-role person, or when the request says so (the console always does, for a mix it is replacing).
        if (request.role is not None and user.role == "custom") or request.custom_role_ids is not None:
            new_custom = []

    updates: dict = {}
    for field in ["username", "role", "is_active"]:
        val = getattr(request, field, None)
        if val is not None:
            updates[field] = val
    changed: dict[str, Any] = {"account_name": user.account_name}
    for field in ["username", "role", "is_active"]:
        if field in updates and updates[field] != getattr(user, field):
            changed[field] = {"before": getattr(user, field), "after": updates[field]}
    if new_custom is not None:
        changed["custom_roles"] = [r.name for r in new_custom]

    if updates:
        updates["updated_at"] = datetime.now(UTC)
        # The user was loaded above with this tenant's id, but the UPDATE carries it too: `users` has no row-level security, so the tenant
        # must not depend on the order of the statements.
        await db.execute(update(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id).values(**updates))
    if new_custom is not None:
        from app.models.rbac import Role, UserRole  # noqa: PLC0415

        mine = select(Role.id).where(Role.tenant_id == current_user.tenant_id, Role.is_system.is_(False))
        await db.execute(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id.in_(mine)))
        for role in new_custom:
            db.add(UserRole(user_id=user_id, role_id=role.id, assigned_by=current_user.user_id))
    if updates or new_custom is not None:
        if len(changed) > 1:  # something actually changed, not only a request that repeated what was already so
            await _audit_user(db, current_user, "user:updated", user_id, changed)
        await db.commit()
        await db.refresh(user)

    return await _user_out(db, current_user.tenant_id, user)


class ResetPasswordRequest(BaseModel):
    new_password: str


class AdminActionResponse(BaseModel):
    done: bool
    detail: str


async def _user_the_caller_may_manage(db: Any, current_user: Any, user_id: uuid.UUID) -> User:
    """The same guards as update_user: same tenant, and never someone who holds more power than the caller."""
    user = (await db.execute(select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not await _may_manage(db, current_user, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot manage a user whose role grants more than your own.")
    return user


@router.post("/me/users/{user_id}/sign-out", response_model=AdminActionResponse)
async def sign_user_out_everywhere(
    user_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> AdminActionResponse:
    """End every session this person holds (a lost laptop, someone who left). They can sign in again unless the account is also deactivated."""
    from app.core.token_revocation import RevocationUnavailable, sign_out_everywhere  # noqa: PLC0415

    user = await _user_the_caller_may_manage(db, current_user, user_id)
    try:
        await sign_out_everywhere(user.id)
    except RevocationUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not end their sessions: the revocation store is unavailable. Try again.",
        ) from None
    await _audit_user(db, current_user, "user:signed_out_everywhere", user.id, {"account_name": user.account_name})
    await db.commit()
    logger.warning("user signed out everywhere", extra={"acting_user": str(current_user.user_id), "target_user": str(user.id)})
    return AdminActionResponse(done=True, detail="Every session of this person was ended.")


@router.post("/me/users/{user_id}/password", response_model=AdminActionResponse)
async def reset_user_password(
    user_id: uuid.UUID,
    request: ResetPasswordRequest,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> AdminActionResponse:
    """Set a new password for a person (they forgot it) and end all their sessions. Someone resetting their OWN password here is refused: use the change-password route, which asks for the current one."""
    from app.core.password_policy import password_problem  # noqa: PLC0415
    from app.core.token_revocation import RevocationUnavailable, sign_out_everywhere  # noqa: PLC0415

    user = await _user_the_caller_may_manage(db, current_user, user_id)
    if user.id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Use Change password for your own account; it asks for the current password."
        )
    problem = password_problem(request.new_password)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)
    await db.execute(
        update(User)
        .where(User.id == user.id, User.tenant_id == current_user.tenant_id)
        .values(hashed_password=get_password_hash(request.new_password), updated_at=datetime.now(UTC))
    )
    await _audit_user(
        db, current_user, "user:password_reset", user.id, {"account_name": user.account_name}
    )  # the new password is never recorded
    await db.commit()
    logger.warning("user password reset by an administrator", extra={"acting_user": str(current_user.user_id), "target_user": str(user.id)})
    try:
        await sign_out_everywhere(user.id)
    except RevocationUnavailable:
        return AdminActionResponse(
            done=True,
            detail="Password reset, but their existing sessions could not be ended right now (the revocation store is unavailable). Use Sign out everywhere again shortly.",
        )
    return AdminActionResponse(done=True, detail="Password reset. Their sessions were ended: they sign in with the new password.")


@router.delete("/me/users/{user_id}", response_model=AdminActionResponse)
async def delete_user(
    user_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> AdminActionResponse:
    """Remove a person from the workspace for good: their sessions end, their passkeys and role assignments go. Refused for yourself and for the only active administrator. If cases, notes or audit entries still name them the database refuses; disable them instead (they keep their history and cannot sign in)."""
    from app.core.token_revocation import RevocationUnavailable, sign_out_everywhere  # noqa: PLC0415
    from app.models.rbac import UserRole  # noqa: PLC0415
    from app.models.responder import PasskeyCredential  # noqa: PLC0415

    user = await _user_the_caller_may_manage(db, current_user, user_id)
    if user.id == current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot delete your own account.")
    await _refuse_if_last_admin(db, current_user.tenant_id, user, "Deleting this account")
    try:
        await sign_out_everywhere(user.id)
    except RevocationUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not end their sessions first: the revocation store is unavailable. Nothing was deleted. Try again.",
        ) from None
    name = user.account_name
    try:
        await db.execute(delete(PasskeyCredential).where(PasskeyCredential.user_id == user.id))
        await db.execute(delete(UserRole).where(UserRole.user_id == user.id))
        await db.execute(delete(User).where(User.id == user.id, User.tenant_id == current_user.tenant_id))
        await _audit_user(db, current_user, "user:deleted", user_id, {"account_name": name, "role": user.role})
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This person cannot be deleted because cases, notes or audit entries still refer to them. Disable the account instead: they keep their history and cannot sign in.",
        ) from None
    logger.warning(
        "user deleted by an administrator",
        extra={"acting_user": str(current_user.user_id), "deleted_user": str(user_id), "account_name": name},
    )
    return AdminActionResponse(done=True, detail=f"{name} was deleted.")


@router.post("/me/users/{user_id}/reset-mfa", response_model=AdminActionResponse)
async def reset_user_mfa(
    user_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: DBSession,
) -> AdminActionResponse:
    """Remove every passkey and the authenticator app this person has set up (a lost phone or security key) and end their sessions. They sign in with their password and can set up a new second factor from Settings > Profile."""
    from app.core.token_revocation import RevocationUnavailable, sign_out_everywhere  # noqa: PLC0415
    from app.models.responder import PasskeyCredential  # noqa: PLC0415
    from app.services import totp_store  # noqa: PLC0415

    user = await _user_the_caller_may_manage(db, current_user, user_id)
    result = await db.execute(
        update(PasskeyCredential)
        .where(
            PasskeyCredential.user_id == user.id,
            PasskeyCredential.tenant_id == current_user.tenant_id,
            PasskeyCredential.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    count = result.rowcount or 0
    # A lost phone also holds the authenticator app: removing only the passkeys left a code prompt nobody could answer, and a stolen phone still able to.
    totp_removed = await totp_store.remove(db, user.id, current_user.tenant_id)
    await _audit_user(
        db,
        current_user,
        "user:mfa_reset",
        user.id,
        {"account_name": user.account_name, "passkeys_removed": count, "totp_removed": totp_removed},
    )
    await db.commit()
    logger.warning(
        "user passkeys removed by an administrator",
        extra={"acting_user": str(current_user.user_id), "target_user": str(user.id), "passkeys": count},
    )
    try:
        await sign_out_everywhere(user.id)
    except RevocationUnavailable:
        return AdminActionResponse(
            done=True,
            detail=f"{count} passkey(s){' and the authenticator app' if totp_removed else ''} removed, but their sessions could not be ended right now (the revocation store is unavailable). Use Sign out everywhere again shortly.",
        )
    return AdminActionResponse(
        done=True,
        detail=f"{count} passkey(s){' and the authenticator app' if totp_removed else ''} removed and their sessions ended. They sign in with their password and can set up a new second factor.",
    )
