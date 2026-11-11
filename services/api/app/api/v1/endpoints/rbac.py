"""RBAC endpoints — role & permission management.

Roles are tenant-scoped.  Permissions are platform-wide and read-only.

Requires:
  - ``roles:read``  to list / inspect roles and permissions
  - ``roles:write`` to create / update / delete roles and assign users
  - ``users:write`` to assign / revoke roles from users
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.deps import AuthUser, require_permission
from app.db.rls import TenantDBSession
from app.models.audit import AuditLog
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.tenant import Tenant, User
from app.services import role_history
from app.services.audit import emit_audit
from app.services.role_nav import clean_hidden_nav
from app.services.sso_default_role import ALLOWED_BUILTIN
from app.services.sso_default_role import KEY as SSO_DEFAULT_KEY
from app.services.sso_default_role import effective as effective_default_role
from app.services.sso_default_role import stored as stored_default_role

router = APIRouter(prefix="/rbac", tags=["rbac"])


# ──────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────


class PermissionOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    category: str | None

    model_config = {"from_attributes": True}


class RoleIn(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[uuid.UUID] = []
    # Sections ("section:Automation") and pages ("/settings/mfa") people in this role do not see in the console. A view setting; permissions are what the server enforces.
    hidden_nav: list[str] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    permission_ids: list[uuid.UUID] | None = None
    hidden_nav: list[str] | None = None


class RoleOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    hidden_nav: list[str] = []
    permissions: list[PermissionOut] = []

    model_config = {"from_attributes": True}


class UserRoleAssignment(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID


class UserRoleOut(BaseModel):
    user_id: uuid.UUID
    role_id: uuid.UUID
    role_name: str

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# Permissions (platform-wide, read-only)
# ──────────────────────────────────────────────


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
    db: TenantDBSession,
    category: str | None = None,
) -> list[PermissionOut]:
    """List all available permissions."""
    q = select(Permission).order_by(Permission.category, Permission.name)
    if category:
        q = q.where(Permission.category == category)
    result = await db.execute(q)
    return [PermissionOut.model_validate(p) for p in result.scalars().all()]


# The built-in roles an administrator can hand out from Settings. Their permissions are fixed in code (app.core.security.ROLE_PERMISSIONS), the same list the access checks use,
# so what is shown here is exactly what the role grants. platform_admin and the legacy admin role are never listed: they are not something a workspace hands out.
BUILTIN_ASSIGNABLE: tuple[tuple[str, str, str], ...] = (
    ("viewer", "Viewer", "Can look, cannot change anything."),
    ("soc_analyst", "SOC analyst", "Works alerts and cases."),
    ("threat_hunter", "Threat hunter", "Analyst who also runs hunts and queries."),
    ("soc_lead", "SOC lead", "Analyst who also manages the team and rules."),
    ("tenant_admin", "Administrator", "Manages the workspace, its members and settings."),
)


class BuiltinRoleOut(BaseModel):
    key: str
    label: str
    description: str
    permissions: list[str]


@router.get("/builtin-roles", response_model=list[BuiltinRoleOut])
async def list_builtin_roles(
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
) -> list[BuiltinRoleOut]:
    """The built-in roles and exactly what each grants. They cannot be edited (they are part of the product); make a custom role from one to change it."""
    from app.core.security import ROLE_PERMISSIONS  # noqa: PLC0415

    return [
        BuiltinRoleOut(key=key, label=label, description=hint, permissions=sorted(ROLE_PERMISSIONS[key]))
        for key, label, hint in BUILTIN_ASSIGNABLE
    ]


class SsoDefaultOut(BaseModel):
    sso_configured: bool  # Microsoft sign-in is set up on this server
    applies_here: bool  # and it creates new people in THIS workspace
    role: str
    custom_role_id: uuid.UUID | None
    source: str  # "setting" (chosen here) or "server" (the MS_SSO_NEW_USER_ROLE setting)
    allowed_builtin: list[str]


class SsoDefaultIn(BaseModel):
    role: str
    custom_role_id: uuid.UUID | None = None


def _sso_state() -> tuple[bool, Any]:
    from app.api.v1.endpoints.sso_microsoft import load_config  # noqa: PLC0415

    cfg = load_config()
    return cfg is not None, cfg


@router.get("/sso-default", response_model=SsoDefaultOut)
async def get_sso_default(
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
    db: TenantDBSession,
) -> SsoDefaultOut:
    """The role a person gets the first time they sign in with Microsoft without an account."""
    configured, cfg = _sso_state()
    tenant = await db.get(Tenant, current_user.tenant_id)
    role, custom, source = effective_default_role(tenant.settings if tenant is not None else None, cfg.new_user_role if cfg else "viewer")
    return SsoDefaultOut(
        sso_configured=configured,
        applies_here=bool(cfg and cfg.home_tenant == current_user.tenant_id),
        role=role,
        custom_role_id=custom,
        source=source,
        allowed_builtin=list(ALLOWED_BUILTIN),
    )


@router.put("/sso-default", response_model=SsoDefaultOut)
async def set_sso_default(
    body: SsoDefaultIn,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:write"))],
    db: TenantDBSession,
) -> SsoDefaultOut:
    """Choose the role new Microsoft sign-ins get: a built-in role (never an administrator) or one of this workspace's custom roles, which then stands alone."""
    configured, cfg = _sso_state()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Microsoft sign-in is not set up on this server, so there is nothing to choose a role for.",
        )
    if cfg.home_tenant != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Microsoft sign-in creates new people in a different workspace. Choose the role there.",
        )
    if body.role not in ALLOWED_BUILTIN:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose Viewer, SOC analyst, Threat hunter or SOC lead (or a custom role). Administrators are never made automatically.",
        )
    if not current_user.can_grant_role(body.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot choose a role that grants more than your own.")
    role = body.role
    if body.custom_role_id is not None:
        custom = await _get_role_or_404(db, body.custom_role_id, current_user.tenant_id)
        _require_permissions_held(current_user, [p.name for p in await _load_role_permissions(db, custom.id)])
        role = "custom"  # a custom role stands alone: a person has one role
    tenant = await db.get(Tenant, current_user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    before = effective_default_role(tenant.settings, cfg.new_user_role)
    tenant.settings = {**(tenant.settings or {}), SSO_DEFAULT_KEY: stored_default_role(role, body.custom_role_id)}
    await emit_audit(
        db=db,
        tenant_id=tenant.id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action="sso:default_role_changed",
        resource="sso_default_role",
        resource_id=str(tenant.id),
        changes={
            "before": {"role": before[0], "custom_role_id": str(before[1]) if before[1] else None},
            "after": stored_default_role(role, body.custom_role_id),
        },
    )
    await db.commit()
    return SsoDefaultOut(
        sso_configured=True,
        applies_here=True,
        role=role,
        custom_role_id=body.custom_role_id,
        source="setting",
        allowed_builtin=list(ALLOWED_BUILTIN),
    )


# ──────────────────────────────────────────────
# Roles (tenant-scoped)
# ──────────────────────────────────────────────


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
    db: TenantDBSession,
) -> list[RoleOut]:
    """List all roles for the current tenant."""
    result = await db.execute(
        select(Role)
        .where(Role.tenant_id == current_user.tenant_id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
        .order_by(Role.name)
    )
    roles = result.scalars().all()
    out: list[RoleOut] = []
    for role in roles:
        perms = [PermissionOut.model_validate(rp.permission) for rp in role.role_permissions]
        out.append(
            RoleOut(
                id=role.id,
                tenant_id=role.tenant_id,
                name=role.name,
                description=role.description,
                is_system=role.is_system,
                hidden_nav=list(role.hidden_nav or []),
                permissions=perms,
            )
        )
    return out


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleIn,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:write"))],
    db: TenantDBSession,
) -> RoleOut:
    """Create a custom role for the current tenant."""
    # Check name uniqueness
    existing = await db.execute(select(Role).where(Role.tenant_id == current_user.tenant_id, Role.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Role '{body.name}' already exists")

    perms_to_attach = await _resolve_permissions(db, body.permission_ids)
    _require_permissions_held(current_user, [p.name for p in perms_to_attach])

    role = Role(
        tenant_id=current_user.tenant_id,
        name=body.name,
        description=body.description,
        is_system=False,
        hidden_nav=clean_hidden_nav(body.hidden_nav),
    )
    db.add(role)
    await db.flush()  # get role.id

    # Attach permissions
    for perm in perms_to_attach:
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    await _audit_role(
        db, current_user, "role:created", role.id, {"name": role.name, "permissions": sorted(p.name for p in perms_to_attach)}
    )
    await db.commit()
    await db.refresh(role)

    return RoleOut(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        hidden_nav=list(role.hidden_nav or []),
        permissions=[PermissionOut.model_validate(p) for p in perms_to_attach],
    )


@router.get("/roles/{role_id}", response_model=RoleOut)
async def get_role(
    role_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
    db: TenantDBSession,
) -> RoleOut:
    role = await _get_role_or_404(db, role_id, current_user.tenant_id)
    perms = await _load_role_permissions(db, role.id)
    return RoleOut(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        hidden_nav=list(role.hidden_nav or []),
        permissions=perms,
    )


class RoleChangeOut(BaseModel):
    at: str | None
    by: str | None
    action: str
    summary: str


@router.get("/roles/{role_id}/history", response_model=list[RoleChangeOut])
async def role_history_list(
    role_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
    db: TenantDBSession,
) -> list[RoleChangeOut]:
    """The last ten changes to this role and to who holds it, newest first, in plain words (from the audit log)."""
    await _get_role_or_404(db, role_id, current_user.tenant_id)
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == current_user.tenant_id, AuditLog.resource == "role", AuditLog.resource_id == str(role_id))
        .order_by(AuditLog.created_at.desc())
        .limit(role_history.SHOWN)
    )
    entries = [
        {"created_at": e.created_at, "actor_email": e.actor_email, "action": e.action, "changes": e.changes} for e in result.scalars().all()
    ]
    return [RoleChangeOut(**row) for row in role_history.rows(entries)]


class RoleHolderOut(BaseModel):
    user_id: str
    name: str
    email: str | None
    since: str | None
    active: bool


@router.get("/roles/{role_id}/holders", response_model=list[RoleHolderOut])
async def role_holders(
    role_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:read"))],
    db: TenantDBSession,
) -> list[RoleHolderOut]:
    """Who holds this role now, the longest holder first: only this organization's own users, with since when and whether the account is still active."""
    await _get_role_or_404(db, role_id, current_user.tenant_id)
    result = await db.execute(
        select(User.id, User.username, User.account_name, User.email, User.is_active, UserRole.assigned_at)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == role_id, User.tenant_id == current_user.tenant_id)
        .limit(500)
    )
    found = [
        {"user_id": r[0], "username": r[1], "account_name": r[2], "email": r[3], "is_active": r[4], "assigned_at": r[5]}
        for r in result.all()
    ]
    return [RoleHolderOut(**h) for h in role_history.holders(found)]


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: uuid.UUID,
    body: RoleUpdate,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:write"))],
    db: TenantDBSession,
) -> RoleOut:
    role = await _get_role_or_404(db, role_id, current_user.tenant_id)

    if role.is_system:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System roles cannot be modified")

    before_name = role.name
    before_permissions = {p.name for p in await _load_role_permissions(db, role.id)}
    perms = None
    if body.permission_ids is not None:
        perms = await _resolve_permissions(db, body.permission_ids)
        _require_permissions_held(current_user, [p.name for p in perms])
        # Nobody edits a role that already holds something they do not (a tenant_admin could otherwise re-name or strip a platform role).
        _require_permissions_held(current_user, [p.name for p in await _load_role_permissions(db, role.id)])

    if body.name is not None:
        role.name = body.name
    if body.description is not None:
        role.description = body.description
    if body.hidden_nav is not None:
        role.hidden_nav = clean_hidden_nav(body.hidden_nav)

    if perms is not None:
        # Replace permissions
        await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for perm in perms:
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))

    after_permissions = {p.name for p in perms} if perms is not None else before_permissions
    await _audit_role(
        db,
        current_user,
        "role:updated",
        role.id,
        {
            "name": {"before": before_name, "after": role.name},
            "permissions_added": sorted(after_permissions - before_permissions),
            "permissions_removed": sorted(before_permissions - after_permissions),
        },
    )
    await db.commit()
    await db.refresh(role)
    perms_out = await _load_role_permissions(db, role.id)
    return RoleOut(
        id=role.id,
        tenant_id=role.tenant_id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        hidden_nav=list(role.hidden_nav or []),
        permissions=perms_out,
    )


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_role(
    role_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("roles:write"))],
    db: TenantDBSession,
) -> None:
    role = await _get_role_or_404(db, role_id, current_user.tenant_id)
    if role.is_system:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="System roles cannot be deleted")
    await _audit_role(
        db,
        current_user,
        "role:deleted",
        role.id,
        {"name": role.name, "permissions": sorted(p.name for p in await _load_role_permissions(db, role.id))},
    )
    await db.delete(role)
    await db.commit()


# ──────────────────────────────────────────────
# User ↔ Role assignments
# ──────────────────────────────────────────────


@router.get("/users/{user_id}/roles", response_model=list[UserRoleOut])
async def get_user_roles(
    user_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("users:read"))],
    db: TenantDBSession,
) -> list[UserRoleOut]:
    """List roles assigned to a user within the current tenant."""
    result = await db.execute(
        select(UserRole, Role.name)
        .join(Role, Role.id == UserRole.role_id)
        .where(
            UserRole.user_id == user_id,
            Role.tenant_id == current_user.tenant_id,
        )
    )
    rows = result.all()
    return [UserRoleOut(user_id=row.UserRole.user_id, role_id=row.UserRole.role_id, role_name=row.name) for row in rows]


@router.post("/users/{user_id}/roles", response_model=UserRoleOut, status_code=status.HTTP_201_CREATED)
async def assign_role(
    user_id: uuid.UUID,
    body: UserRoleAssignment,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: TenantDBSession,
) -> UserRoleOut:
    """Assign a role to a user."""
    if body.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="user_id mismatch")

    role = await _get_role_or_404(db, body.role_id, current_user.tenant_id)
    # Assigning a role hands out everything in it: the caller must hold all of it.
    _require_permissions_held(current_user, [p.name for p in await _load_role_permissions(db, role.id)])

    # Ensure the target user belongs to this tenant
    user_res = await db.execute(select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id))
    target = user_res.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in tenant")
    # A person has ONE role. Only someone whose role is already "custom" can be given another custom role here (it replaces the first); a person with a built-in role changes
    # role under Settings > Workspace > Edit, which keeps the built-in role and the custom role in step.
    if target.role != "custom":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A person has one role. Change their role to this custom role under Settings > Workspace > Edit.",
        )
    await db.execute(
        delete(UserRole).where(
            UserRole.user_id == user_id,
            UserRole.role_id.in_(select(Role.id).where(Role.tenant_id == current_user.tenant_id, Role.is_system.is_(False))),
        )
    )

    # Upsert
    existing = await db.execute(select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role.id))
    if existing.scalar_one_or_none() is not None:
        return UserRoleOut(user_id=user_id, role_id=role.id, role_name=role.name)

    assignment = UserRole(user_id=user_id, role_id=role.id, assigned_by=current_user.user_id)
    db.add(assignment)
    await _audit_role(db, current_user, "role:assigned", role.id, {"user_id": str(user_id), "role_name": role.name})
    await db.commit()
    return UserRoleOut(user_id=user_id, role_id=role.id, role_name=role.name)


@router.delete("/users/{user_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_role(
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    current_user: Annotated[AuthUser, Depends(require_permission("users:write"))],
    db: TenantDBSession,
) -> None:
    """Revoke a role from a user.

    Both the role and the user must belong to the caller's tenant, exactly as assign_role requires. This used to delete the assignment by the two ids alone (user_roles has no tenant column to filter on), so any tenant admin with users:write could strip any role from any user of ANY tenant, shown on real
    Postgres by the two-tenant flows (tenant B removed tenant A's role assignment, HTTP 204). A role or user that is not this tenant's is the same 404 as one that does not exist."""
    revoked_role = await _get_role_or_404(db, role_id, current_user.tenant_id)
    user_res = await db.execute(select(User).where(User.id == user_id, User.tenant_id == current_user.tenant_id))
    if user_res.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found in tenant")
    await db.execute(delete(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_id))
    await _audit_role(db, current_user, "role:revoked", role_id, {"user_id": str(user_id), "role_name": revoked_role.name})
    await db.commit()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


async def _get_role_or_404(db: AsyncSession, role_id: uuid.UUID, tenant_id: uuid.UUID) -> Role:
    result = await db.execute(select(Role).where(Role.id == role_id, Role.tenant_id == tenant_id))
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return role


def _require_permissions_held(current_user: Any, names: list[str]) -> None:
    """Nobody attaches to a role, or assigns through one, a permission they do not hold themselves (database roles are consulted by has_permission_db). A platform permission needs that exact permission."""
    for name in names:
        held = current_user.holds_wildcard() if name == "*" else current_user.holds(name)
        if not held:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"You cannot grant the permission {name!r}: you do not hold it yourself."
            )


async def _audit_role(db: AsyncSession, current_user: AuthUser, action: str, role_id: uuid.UUID, changes: dict) -> None:
    """One audit entry for a change to a custom role or to who holds one: what changed in names (never a secret). A role gaining or losing permissions is exactly what an investigation after an incident asks about."""
    await emit_audit(
        db=db,
        tenant_id=current_user.tenant_id,
        actor_id=current_user.user_id,
        actor_email=current_user.email,
        action=action,
        resource="role",
        resource_id=str(role_id),
        changes=changes,
    )


async def _resolve_permissions(db: AsyncSession, permission_ids: list[uuid.UUID]) -> list[Permission]:
    if not permission_ids:
        return []
    result = await db.execute(select(Permission).where(Permission.id.in_(permission_ids)))
    found = result.scalars().all()
    if len(found) != len(permission_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more permission IDs are invalid")
    return list(found)


async def _load_role_permissions(db: AsyncSession, role_id: uuid.UUID) -> list[PermissionOut]:
    result = await db.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.category, Permission.name)
    )
    return [PermissionOut.model_validate(p) for p in result.scalars().all()]
