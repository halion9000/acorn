"""Set up, check and turn off the authenticator-app code a person's password sign-in asks for (improvement A13).

``GET /auth/totp``           whether it is on, and how many recovery codes are left
``POST /auth/totp/enrol``    start: a new secret, as text and as the address an authenticator app reads (nothing changes about signing in yet)
``POST /auth/totp/confirm``  the person types a code from the app: it is then ON, and the ten recovery codes are returned ONCE
``POST /auth/totp/recovery``  ten new recovery codes (the old ones stop working); needs the current password AND a current code, like turning it off
``POST /auth/totp/disable``  turn it off; needs the current password AND a current code (or a recovery code), so a stolen session alone cannot remove the protection

Signing in with a password when it is on: ``POST /auth/login`` also takes ``totp_code`` (an app code or a recovery code); without it the answer is 428 "enter the code" (after the password was right).
Passkeys and Microsoft sign-in are separate ways in and are not changed by this.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.v1.deps import DBSession, SessionUser
from app.core.security import verify_password_or_equalise
from app.models.tenant import User
from app.services import login_throttle, totp_store
from app.services.audit import emit_audit

router = APIRouter(prefix="/auth/totp", tags=["auth"])


class TotpStatus(BaseModel):
    enabled: bool
    recovery_codes_left: int = 0


class EnrolOut(BaseModel):
    secret: str
    otpauth_uri: str


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class ConfirmOut(BaseModel):
    recovery_codes: list[str]
    note: str = "Keep these somewhere safe. Each works once if you lose your phone. They are not shown again."


class DisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=32, description="A current code from the app, or an unused recovery code.")


class Done(BaseModel):
    ok: bool = True


async def _user(db: DBSession, who: SessionUser) -> User:
    user = (await db.execute(select(User).where(User.id == who.user_id, User.is_active.is_(True)))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such account")
    return user


@router.get("", response_model=TotpStatus)
async def totp_status(db: DBSession, who: SessionUser) -> TotpStatus:
    user = await _user(db, who)
    row = await totp_store.load(db, user.id, user.tenant_id)
    if row is None or row.confirmed_at is None:
        return TotpStatus(enabled=False)
    return TotpStatus(enabled=True, recovery_codes_left=len(row.recovery_hashes or []))


@router.post("/enrol", response_model=EnrolOut)
async def enrol(db: DBSession, who: SessionUser) -> EnrolOut:
    user = await _user(db, who)
    try:
        secret, uri = await totp_store.start_enrolment(db, user.id, user.tenant_id, user.email or user.account_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    await db.commit()
    return EnrolOut(secret=secret, otpauth_uri=uri)


@router.post("/confirm", response_model=ConfirmOut)
async def confirm(body: CodeIn, request: Request, db: DBSession, who: SessionUser) -> ConfirmOut:
    user = await _user(db, who)
    codes = await totp_store.confirm(db, user.id, user.tenant_id, body.code)
    if codes is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code is not right. Check the time on your phone and try the next code.")
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.id, action="auth:totp_enabled", resource="user", resource_id=str(user.id), changes={}, request=request)
    await db.commit()
    return ConfirmOut(recovery_codes=codes)


@router.post("/disable", response_model=Done)
async def disable(body: DisableIn, request: Request, db: DBSession, who: SessionUser) -> Done:
    user = await _user(db, who)
    # Wrong password or code is counted like a failed sign-in, so this cannot be used to guess either.
    await login_throttle.ensure_not_locked(db, user.account_name, None)
    if not verify_password_or_equalise(body.password, user.hashed_password) or await totp_store.check_code(db, user.id, user.tenant_id, body.code) is None:
        await login_throttle.record_failure(db, user.account_name, None)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The password or the code is not right.")
    await totp_store.remove(db, user.id, user.tenant_id)
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.id, action="auth:totp_disabled", resource="user", resource_id=str(user.id), changes={}, request=request)
    await db.commit()
    return Done()



@router.post("/recovery", response_model=ConfirmOut)
async def new_recovery_codes(body: DisableIn, request: Request, db: DBSession, who: SessionUser) -> ConfirmOut:
    """Replace the recovery codes (used up, or lost). Counted like a failed sign-in when the password or code is wrong, so it cannot be used to guess either."""
    user = await _user(db, who)
    await login_throttle.ensure_not_locked(db, user.account_name, None)
    if not verify_password_or_equalise(body.password, user.hashed_password) or await totp_store.check_code(db, user.id, user.tenant_id, body.code) is None:
        await login_throttle.record_failure(db, user.account_name, None)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="The password or the code is not right.")
    codes = await totp_store.new_recovery_codes(db, user.id, user.tenant_id)
    if codes is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The authenticator app is not on, so there are no recovery codes to replace.")
    await emit_audit(db=db, tenant_id=user.tenant_id, actor_id=user.id, action="auth:totp_recovery_codes_replaced", resource="user", resource_id=str(user.id), changes={}, request=request)
    await db.commit()
    return ConfirmOut(recovery_codes=codes)
