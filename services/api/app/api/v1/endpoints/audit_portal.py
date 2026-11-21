"""Auditor access to an audit, and the files an audit keeps (Compliance > Audits).

Two sets of routes:
* ``/compliance/audits/{id}/auditors`` and ``/files`` for staff (``reports:read`` to look, ``reports:write`` to change): link a person who holds the ``auditor`` role to an audit, take the link away, and
  list, upload, download and delete the audit's files.
* ``/audit-portal/audits`` for the auditor (role ``auditor``, with an authenticator app set up): only the audits linked to them, the requests on those audits, the files, and a way to upload a file or accept
  a request that staff marked provided. Which audits an auditor may open comes from the ``audit_auditors`` table, never from the request: asking for another audit's id gives "not found". The role reaches
  nothing but these routes (app/services/client_portal.py ``enforce_reach``).

Files are kept in the database, at most 10 MB each and 50 per audit, always served as a download of unknown type (never opened in the browser) so an uploaded page cannot run.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import defer

from app.api.v1.deps import AuthUser, DBSession, require_permission
from app.api.v1.endpoints import audits as audits_ep
from app.api.v1.endpoints.compliance import ScopeTenant
from app.core.account_names import InvalidAccountName, validate_account_name
from app.core.emails import normalize_email
from app.core.security import get_password_hash
from app.db.rls_scope import acting_as_tenant, cross_tenant_reads
from app.models.tenant import User
from app.models.trust_audit import Audit, AuditAuditor, AuditFile, AuditRequest
from app.services import client_portal, totp_store
from app.services.account_names import account_name_taken
from app.services import compliance_audit as audit_trail

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_AUDIT = 50

staff_router = APIRouter(prefix="/compliance/audits", tags=["compliance"])
router = APIRouter(prefix="/audit-portal", tags=["audit-portal"])


# ----------------------------------------------------------------------------- shared pieces


class FileIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1)
    request_id: uuid.UUID | None = None


class FileOut(BaseModel):
    id: uuid.UUID
    name: str
    size_bytes: int
    request_id: uuid.UUID | None
    uploaded_by: str | None
    by_auditor: bool
    created_at: datetime


class AuditorOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    name: str
    since: datetime


class AuditorIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class InviteIn(BaseModel):
    account_name: str = Field(min_length=3, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    name: str | None = Field(default=None, max_length=100)


class InviteOut(BaseModel):
    auditors: list[AuditorOut]
    temporary_password: str


class AuditorRequestPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|accepted)$")
    note: str | None = Field(default=None, max_length=4000)


def clean_file_name(name: str) -> str:
    """The file's name without any folder part or odd characters (pure). Never empty."""
    base = re.split(r"[\\/]", name.strip())[-1]
    base = re.sub(r"[^\w.\- ()]", "_", base).strip(" .")
    return (base or "file")[:255]


def decode_content(text: str) -> bytes:
    """The bytes of a base64 upload, or an HTTPException saying why not (empty, not base64, over the limit). Checks the size before decoding the whole text."""
    if len(text) > (MAX_FILE_BYTES * 4) // 3 + 8:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="That file is over 10 MB.")
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The file content is not valid base64.") from None
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="That file is over 10 MB.")
    return data


def _file_out(f: AuditFile) -> FileOut:
    return FileOut(
        id=f.id, name=f.name, size_bytes=f.size_bytes, request_id=f.request_id, uploaded_by=f.uploaded_by, by_auditor=f.by_auditor, created_at=f.created_at
    )


async def _files(db: DBSession, tenant: uuid.UUID, audit_id: uuid.UUID) -> list[FileOut]:
    rows = (
        (await db.execute(select(AuditFile).options(defer(AuditFile.content)).where(AuditFile.audit_id == audit_id, AuditFile.tenant_id == tenant).order_by(AuditFile.created_at.desc())))
        .scalars()
        .all()
    )
    return [_file_out(f) for f in rows]


async def _store_file(db: DBSession, tenant: uuid.UUID, a: Audit, body: FileIn, who: str | None, by_auditor: bool) -> AuditFile:
    if a.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That audit is complete and cannot be changed.")
    data = decode_content(body.content_base64)
    count = (await db.execute(select(func.count()).select_from(AuditFile).where(AuditFile.audit_id == a.id, AuditFile.tenant_id == tenant))).scalar_one()
    if count >= MAX_FILES_PER_AUDIT:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"An audit keeps at most {MAX_FILES_PER_AUDIT} files.")
    if body.request_id is not None:
        found = (
            await db.execute(select(AuditRequest.id).where(AuditRequest.id == body.request_id, AuditRequest.audit_id == a.id, AuditRequest.tenant_id == tenant))
        ).scalar_one_or_none()
        if found is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    f = AuditFile(
        id=uuid.uuid4(),
        tenant_id=tenant,
        audit_id=a.id,
        request_id=body.request_id,
        name=clean_file_name(body.name),
        content_type="application/octet-stream",
        size_bytes=len(data),
        content=data,
        uploaded_by=who,
        by_auditor=by_auditor,
    )
    db.add(f)
    return f


def _download(f: AuditFile) -> Response:
    return Response(
        content=f.content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{f.name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


async def _file(db: DBSession, tenant: uuid.UUID, audit_id: uuid.UUID, file_id: uuid.UUID) -> AuditFile:
    f = (await db.execute(select(AuditFile).where(AuditFile.id == file_id, AuditFile.audit_id == audit_id, AuditFile.tenant_id == tenant))).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return f


# ----------------------------------------------------------------------------- staff


@staff_router.get("/{audit_id}/auditors", response_model=list[AuditorOut], summary="The people with the auditor role who may open this audit")
async def list_auditors(
    audit_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> list[AuditorOut]:
    await audits_ep._audit(db, tenant, audit_id)
    async with cross_tenant_reads(db):
        rows = (
            await db.execute(
                select(AuditAuditor, User)
                .join(User, User.id == AuditAuditor.user_id)
                .where(AuditAuditor.audit_id == audit_id, AuditAuditor.tenant_id == tenant)
                .order_by(AuditAuditor.created_at)
            )
        ).all()
    return [AuditorOut(user_id=u.id, email=u.email, name=u.username, since=link.created_at) for link, u in rows]


@staff_router.post(
    "/{audit_id}/auditors", response_model=list[AuditorOut], status_code=status.HTTP_201_CREATED, summary="Let a person with the auditor role open this audit"
)
async def add_auditor(
    audit_id: uuid.UUID,
    body: AuditorIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> list[AuditorOut]:
    a = await audits_ep._audit(db, tenant, audit_id)
    email = body.email.strip().lower()
    async with cross_tenant_reads(db):
        person = (await db.execute(select(User).where(func.lower(User.email) == email, User.tenant_id == tenant))).scalar_one_or_none()
    if person is None or person.role != client_portal.AUDITOR_ROLE or not person.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active person with the auditor role has that e-mail address. Create the sign-in first (Settings, Users, role Auditor).",
        )
    have = (await db.execute(select(AuditAuditor).where(AuditAuditor.audit_id == a.id, AuditAuditor.user_id == person.id))).scalar_one_or_none()
    if have is None:
        db.add(AuditAuditor(tenant_id=tenant, audit_id=a.id, user_id=person.id, created_by=getattr(user, "email", None)))
        await audit_trail.note(db, tenant, user, "audit:auditor_added", "audit", a.id, auditor=email)
        await db.commit()
    return await list_auditors(audit_id, tenant, db, user)


@staff_router.post(
    "/{audit_id}/auditors/invite",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a sign-in for an outside auditor and let it open this audit (the temporary password is shown once)",
)
async def invite_auditor(
    audit_id: uuid.UUID,
    body: InviteIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> InviteOut:
    """The new account has the auditor role in this audit's workspace and nothing else; it must set up an authenticator app before the audit opens."""
    user.require_permission("users:write")
    a = await audits_ep._audit(db, tenant, audit_id)
    try:
        name = validate_account_name(body.account_name)
    except InvalidAccountName as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    # An auditor account that no audit opens any more (its access was taken away) is reused instead of refused: new password, linked to this audit.
    leftover = await _unlinked_auditor(db, tenant, name)
    if leftover is None and await account_name_taken(db, name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That account name is already taken. Choose another.")
    if leftover is not None:
        password = secrets.token_urlsafe(15)
        leftover.hashed_password = get_password_hash(password)
        leftover.is_active = True
        if body.name and body.name.strip():
            leftover.username = body.name.strip()[:100]
        db.add(AuditAuditor(tenant_id=tenant, audit_id=a.id, user_id=leftover.id, created_by=getattr(user, "email", None)))
        await db.flush()
        await audit_trail.note(db, tenant, user, "audit:auditor_invited", "audit", a.id, auditor=str(leftover.id), reused=True)
        await db.commit()
        return InviteOut(auditors=await list_auditors(audit_id, tenant, db, user), temporary_password=password)
    email = normalize_email(body.email) if body.email else None
    if email is not None:
        taken = (await db.execute(select(User.id).where(func.lower(User.email) == email).limit(1))).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This email address cannot be used. Choose a different one.")
    password = secrets.token_urlsafe(15)
    person = User(
        id=uuid.uuid4(),
        tenant_id=tenant,
        email=email,
        account_name=name,
        username=(body.name or name).strip()[:100] or name,
        hashed_password=get_password_hash(password),
        role=client_portal.AUDITOR_ROLE,
    )
    db.add(person)
    await db.flush()
    db.add(AuditAuditor(tenant_id=tenant, audit_id=a.id, user_id=person.id, created_by=getattr(user, "email", None)))
    await audit_trail.note(db, tenant, user, "audit:auditor_invited", "audit", a.id, account_name=name)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That account name (or email) was just taken. Choose another.") from None
    return InviteOut(auditors=await list_auditors(audit_id, tenant, db, user), temporary_password=password)


async def _unlinked_auditor(db: Any, tenant: uuid.UUID, name: str) -> Any:
    """An auditor account of this workspace with this name that opens no audit (so it can be reused), else None (pure lookup)."""
    person = (
        await db.execute(select(User).where(func.lower(User.account_name) == name.lower(), User.tenant_id == tenant, User.role == client_portal.AUDITOR_ROLE))
    ).scalar_one_or_none()
    if person is None:
        return None
    links = (await db.execute(select(func.count()).select_from(AuditAuditor).where(AuditAuditor.user_id == person.id))).scalar_one()
    return None if links else person


@staff_router.delete("/{audit_id}/auditors/{user_id}", response_model=list[AuditorOut], summary="Take an auditor's access to this audit away")
async def remove_auditor(
    audit_id: uuid.UUID,
    user_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> list[AuditorOut]:
    a = await audits_ep._audit(db, tenant, audit_id)
    await db.execute(delete(AuditAuditor).where(AuditAuditor.audit_id == a.id, AuditAuditor.user_id == user_id, AuditAuditor.tenant_id == tenant))
    await audit_trail.note(db, tenant, user, "audit:auditor_removed", "audit", a.id, auditor=str(user_id))
    # An auditor account exists only to open audits: with no audit left to open, it is switched off, and its name stays free to use again (a new invite for the same name reuses it).
    person = (await db.execute(select(User).where(User.id == user_id, User.tenant_id == tenant, User.role == client_portal.AUDITOR_ROLE))).scalar_one_or_none()
    if person is not None:
        still = (await db.execute(select(func.count()).select_from(AuditAuditor).where(AuditAuditor.user_id == user_id))).scalar_one()
        if not still:
            person.is_active = False
    await db.commit()
    return await list_auditors(audit_id, tenant, db, user)


@staff_router.get("/{audit_id}/files", response_model=list[FileOut], summary="The files this audit keeps")
async def list_files(
    audit_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> list[FileOut]:
    await audits_ep._audit(db, tenant, audit_id)
    return await _files(db, tenant, audit_id)


@staff_router.post("/{audit_id}/files", response_model=list[FileOut], status_code=status.HTTP_201_CREATED, summary="Add a file to this audit (10 MB at most)")
async def upload_file(
    audit_id: uuid.UUID,
    body: FileIn,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> list[FileOut]:
    a = await audits_ep._audit(db, tenant, audit_id)
    f = await _store_file(db, tenant, a, body, getattr(user, "email", None), by_auditor=False)
    await audit_trail.note(db, tenant, user, "audit:file_added", "audit", a.id, file=f.name, size=f.size_bytes)
    await db.commit()
    return await _files(db, tenant, audit_id)


@staff_router.get("/{audit_id}/files/{file_id}/download", summary="Download one of the audit's files")
async def download_file(
    audit_id: uuid.UUID, file_id: uuid.UUID, tenant: ScopeTenant, db: DBSession, _user: Annotated[AuthUser, Depends(require_permission("reports:read"))]
) -> Response:
    await audits_ep._audit(db, tenant, audit_id)
    return _download(await _file(db, tenant, audit_id, file_id))


@staff_router.delete("/{audit_id}/files/{file_id}", response_model=list[FileOut], summary="Remove one of the audit's files")
async def delete_file(
    audit_id: uuid.UUID,
    file_id: uuid.UUID,
    tenant: ScopeTenant,
    db: DBSession,
    user: Annotated[AuthUser, Depends(require_permission("reports:write"))],
) -> list[FileOut]:
    a = await audits_ep._audit(db, tenant, audit_id)
    if a.status == "complete":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That audit is complete and cannot be changed.")
    f = await _file(db, tenant, audit_id, file_id)
    await audit_trail.note(db, tenant, user, "audit:file_removed", "audit", a.id, file=f.name)
    await db.delete(f)
    await db.commit()
    return await _files(db, tenant, audit_id)


# ----------------------------------------------------------------------------- the auditor's side


async def auditor_user(user: AuthUser, db: DBSession) -> Any:
    """The signed-in auditor: role auditor, a session (never an API key), their own tenant, and an authenticator app set up. Anything else is refused."""
    if user.role != client_portal.AUDITOR_ROLE or user.scopes is not None or user.viewing_other_tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This page is for an auditor's sign-in.")
    user.require_permission("audit_portal:view")
    if not await totp_store.is_enabled(db, user.user_id, user.tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="mfa_setup_required: set up an authenticator app (Settings, Two-step sign-in) before the audit opens."
        )
    return user


Auditor = Annotated[Any, Depends(auditor_user)]


async def linked_audits(db: DBSession, user_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(audit id, tenant id) of every audit linked to this person. Read from the table, never from the request."""
    async with cross_tenant_reads(db):
        rows = (await db.execute(select(AuditAuditor.audit_id, AuditAuditor.tenant_id).where(AuditAuditor.user_id == user_id))).all()
    return [(a, t) for a, t in rows]


async def _my_tenant(db: DBSession, user: Any, audit_id: uuid.UUID) -> uuid.UUID:
    for a, t in await linked_audits(db, user.user_id):
        if a == audit_id:
            return t
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")


@router.get("/audits", response_model=list[audits_ep.AuditOut], summary="The audits you were invited to", dependencies=[Depends(require_permission("audit_portal:view"))])
async def my_audits(user: Auditor, db: DBSession) -> list[audits_ep.AuditOut]:
    out: list[audits_ep.AuditOut] = []
    today = datetime.now(UTC).date()
    for audit_id, tenant in await linked_audits(db, user.user_id):
        async with acting_as_tenant(db, tenant):
            a = (await db.execute(select(Audit).where(Audit.id == audit_id, Audit.tenant_id == tenant))).scalar_one_or_none()
            if a is None:
                continue
            reqs = await audits_ep._requests(db, tenant, a.id)
            out.append(audits_ep._summary(a, reqs, today))
    return sorted(out, key=lambda s: s.created_at, reverse=True)


@router.get("/audits/{audit_id}", response_model=audits_ep.AuditDetail, summary="One audit you were invited to, with its requests", dependencies=[Depends(require_permission("audit_portal:view"))])
async def my_audit(audit_id: uuid.UUID, user: Auditor, db: DBSession) -> audits_ep.AuditDetail:
    tenant = await _my_tenant(db, user, audit_id)
    async with acting_as_tenant(db, tenant):
        return await audits_ep._detail(db, tenant, await audits_ep._audit(db, tenant, audit_id))


@router.patch("/audits/{audit_id}/requests/{request_id}", response_model=audits_ep.AuditDetail, summary="Accept a request staff marked provided, or send it back with a note", dependencies=[Depends(require_permission("audit_portal:view"))])
async def my_request(audit_id: uuid.UUID, request_id: uuid.UUID, body: AuditorRequestPatch, user: Auditor, db: DBSession) -> audits_ep.AuditDetail:
    tenant = await _my_tenant(db, user, audit_id)
    async with acting_as_tenant(db, tenant):
        a = await audits_ep._audit(db, tenant, audit_id)
        if a.status == "complete":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That audit is complete and cannot be changed.")
        r = (await db.execute(select(AuditRequest).where(AuditRequest.id == request_id, AuditRequest.audit_id == audit_id, AuditRequest.tenant_id == tenant))).scalar_one_or_none()
        if r is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
        if body.status == "accepted" and r.status == "open":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nothing has been provided for that request yet.")
        if body.status is not None:
            r.status = body.status  # accepted, or open again so staff provide it again
        if body.note is not None and body.note.strip():
            r.note = (r.note + "\n" if r.note else "") + f"Auditor ({user.email}): {body.note.strip()}"
        r.updated_at = datetime.now(UTC)
        await audit_trail.note(db, tenant, user, "audit:auditor_updated_request", "audit", a.id, request=str(r.id), status=r.status)
        await db.commit()
        return await audits_ep._detail(db, tenant, a)


@router.get("/audits/{audit_id}/files", response_model=list[FileOut], summary="The files kept for an audit you were invited to", dependencies=[Depends(require_permission("audit_portal:view"))])
async def my_files(audit_id: uuid.UUID, user: Auditor, db: DBSession) -> list[FileOut]:
    tenant = await _my_tenant(db, user, audit_id)
    async with acting_as_tenant(db, tenant):
        await audits_ep._audit(db, tenant, audit_id)
        return await _files(db, tenant, audit_id)


@router.post("/audits/{audit_id}/files", response_model=list[FileOut], status_code=status.HTTP_201_CREATED, summary="Upload a file to an audit you were invited to (10 MB at most)", dependencies=[Depends(require_permission("audit_portal:view"))])
async def my_upload(audit_id: uuid.UUID, body: FileIn, user: Auditor, db: DBSession) -> list[FileOut]:
    tenant = await _my_tenant(db, user, audit_id)
    async with acting_as_tenant(db, tenant):
        a = await audits_ep._audit(db, tenant, audit_id)
        f = await _store_file(db, tenant, a, body, getattr(user, "email", None) or user.email, by_auditor=True)
        await audit_trail.note(db, tenant, user, "audit:auditor_uploaded_file", "audit", a.id, file=f.name, size=f.size_bytes)
        await db.commit()
        return await _files(db, tenant, audit_id)


@router.get("/audits/{audit_id}/files/{file_id}/download", summary="Download a file of an audit you were invited to", dependencies=[Depends(require_permission("audit_portal:view"))])
async def my_download(audit_id: uuid.UUID, file_id: uuid.UUID, user: Auditor, db: DBSession) -> Response:
    tenant = await _my_tenant(db, user, audit_id)
    async with acting_as_tenant(db, tenant):
        await audits_ep._audit(db, tenant, audit_id)
        return _download(await _file(db, tenant, audit_id, file_id))
